"""WhatsApp Business provider — abstract contract, Meta Cloud API impl, and mock.

Mirrors the provider pattern in ``messaging_provider.py``. The engagement
engine talks to the ``WhatsAppProvider`` protocol; the concrete backend is
selected at runtime via ``get_whatsapp_provider()``.

    AXIS_WHATSAPP_PROVIDER=meta   -> MetaCloudWhatsAppProvider (real API)
    AXIS_WHATSAPP_PROVIDER=mock   -> MockWhatsAppProvider (default, in-memory)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class WhatsAppSendResult:
    """Outcome of a single send attempt."""

    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Webhook payload models
# ---------------------------------------------------------------------------


class WhatsAppWebhookStatusUpdate(BaseModel):
    """A single status update from Meta's webhook (sent/delivered/read/failed)."""

    message_id: str
    status: Literal["sent", "delivered", "read", "failed"]
    timestamp: datetime
    recipient_id: str
    errors: List[Dict[str, Any]] = Field(default_factory=list)


class WhatsAppWebhookInboundMessage(BaseModel):
    """An inbound text message from a candidate."""

    message_id: str
    from_phone: str
    timestamp: datetime
    text: str


class WhatsAppWebhookPayload(BaseModel):
    """Parsed Meta webhook payload.

    Meta sends batched webhook events. This model normalises the nested
    structure into flat lists the engine can iterate over. Call
    ``WhatsAppWebhookPayload.from_meta_payload(raw)`` to parse.
    """

    status_updates: List[WhatsAppWebhookStatusUpdate] = Field(default_factory=list)
    inbound_messages: List[WhatsAppWebhookInboundMessage] = Field(default_factory=list)

    @classmethod
    def from_meta_payload(cls, raw: Dict[str, Any]) -> "WhatsAppWebhookPayload":
        """Parse the deeply-nested Meta webhook JSON into our flat model.

        Meta's structure:
        {
          "entry": [{
            "changes": [{
              "value": {
                "statuses": [...],
                "messages": [...]
              }
            }]
          }]
        }
        """
        status_updates: List[WhatsAppWebhookStatusUpdate] = []
        inbound_messages: List[WhatsAppWebhookInboundMessage] = []

        for entry in raw.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Status updates (sent, delivered, read, failed)
                for status in value.get("statuses", []):
                    try:
                        status_updates.append(
                            WhatsAppWebhookStatusUpdate(
                                message_id=status["id"],
                                status=status["status"],
                                timestamp=datetime.fromtimestamp(
                                    int(status["timestamp"])
                                ),
                                recipient_id=status.get("recipient_id", ""),
                                errors=status.get("errors", []),
                            )
                        )
                    except (KeyError, ValueError) as exc:
                        log.warning("webhook: skipping malformed status: %r", exc)

                # Inbound text messages
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    try:
                        inbound_messages.append(
                            WhatsAppWebhookInboundMessage(
                                message_id=msg["id"],
                                from_phone=msg["from"],
                                timestamp=datetime.fromtimestamp(
                                    int(msg["timestamp"])
                                ),
                                text=msg.get("text", {}).get("body", ""),
                            )
                        )
                    except (KeyError, ValueError) as exc:
                        log.warning("webhook: skipping malformed message: %r", exc)

        return cls(status_updates=status_updates, inbound_messages=inbound_messages)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


class WhatsAppProvider(Protocol):
    def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        template_params: Dict[str, str],
        language: str = "en",
    ) -> WhatsAppSendResult: ...

    def send_text_message(
        self,
        to_phone: str,
        text: str,
    ) -> WhatsAppSendResult: ...

    def get_message_status(self, message_id: str) -> Dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Real implementation — Meta Cloud API
# ---------------------------------------------------------------------------


class MetaCloudWhatsAppProvider:
    """Sends WhatsApp messages via the Meta Cloud API (v21.0).

    Requires two env vars:
        WHATSAPP_PHONE_NUMBER_ID  — your phone number id from the Meta dashboard
        WHATSAPP_ACCESS_TOKEN     — permanent or system-user access token
    """

    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(self) -> None:
        self._phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
        self._access_token = os.environ["WHATSAPP_ACCESS_TOKEN"]
        self._client = httpx.Client(
            base_url=f"{self.BASE_URL}/{self._phone_number_id}",
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    # -- template message ---------------------------------------------------

    def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        template_params: Dict[str, str],
        language: str = "en",
    ) -> WhatsAppSendResult:
        # Build parameter components for the template body
        components: List[Dict[str, Any]] = []
        if template_params:
            parameters = [
                {"type": "text", "text": v}
                for v in template_params.values()
            ]
            components.append(
                {"type": "body", "parameters": parameters}
            )

        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components,
            },
        }

        return self._send(payload)

    # -- free-form text message ---------------------------------------------

    def send_text_message(self, to_phone: str, text: str) -> WhatsAppSendResult:
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": text},
        }
        return self._send(payload)

    # -- status query -------------------------------------------------------

    def get_message_status(self, message_id: str) -> Dict[str, Any]:
        """Fetch a message by its Meta message ID.

        Note: Meta doesn't expose a dedicated status endpoint; for production
        use, message statuses are tracked via webhooks. This is a convenience
        method that reads the message object itself.
        """
        try:
            resp = self._client.get(
                f"{self.BASE_URL}/{message_id}",
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            log.warning("get_message_status(%s) failed: %r", message_id, exc)
            return {"error": str(exc)}

    # -- internal -----------------------------------------------------------

    def _send(self, payload: Dict[str, Any]) -> WhatsAppSendResult:
        try:
            resp = self._client.post("/messages", json=payload)
            resp.raise_for_status()
            data = resp.json()
            message_id = data.get("messages", [{}])[0].get("id")
            log.info(
                "WhatsApp sent to %s — message_id=%s",
                payload.get("to"),
                message_id,
            )
            return WhatsAppSendResult(success=True, message_id=message_id)
        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            log.error(
                "WhatsApp send failed (HTTP %s): %s",
                exc.response.status_code,
                error_body,
            )
            return WhatsAppSendResult(success=False, error=error_body)
        except httpx.HTTPError as exc:
            log.error("WhatsApp send failed (network): %r", exc)
            return WhatsAppSendResult(success=False, error=str(exc))


# ---------------------------------------------------------------------------
# Real implementation — Twilio WhatsApp API
# ---------------------------------------------------------------------------


class TwilioWhatsAppProvider:
    """Sends WhatsApp messages via the Twilio API.

    Requires three env vars:
        TWILIO_ACCOUNT_SID    — your Twilio account SID
        TWILIO_AUTH_TOKEN      — your Twilio auth token
        TWILIO_WHATSAPP_FROM   — your Twilio WhatsApp number (e.g. "whatsapp:+14155238886")
    """

    BASE_URL = "https://api.twilio.com/2010-04-01/Accounts"

    def __init__(self) -> None:
        self._account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        self._auth_token = os.environ["TWILIO_AUTH_TOKEN"]
        self._from_number = os.environ.get(
            "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
        )
        self._client = httpx.Client(
            auth=(self._account_sid, self._auth_token),
            timeout=30.0,
        )

    def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        template_params: Dict[str, str],
        language: str = "en",
    ) -> WhatsAppSendResult:
        # Twilio sandbox doesn't support template API directly —
        # we send the template content as a text message. For production
        # Twilio Content API templates, swap this to use content SIDs.
        param_values = list(template_params.values())
        body = f"[{template_name}] " + ", ".join(param_values) if param_values else f"[{template_name}]"
        return self._send(to_phone, body)

    def send_text_message(self, to_phone: str, text: str) -> WhatsAppSendResult:
        return self._send(to_phone, text)

    def get_message_status(self, message_id: str) -> Dict[str, Any]:
        try:
            resp = self._client.get(
                f"{self.BASE_URL}/{self._account_sid}/Messages/{message_id}.json"
            )
            resp.raise_for_status()
            data = resp.json()
            return {"id": message_id, "status": data.get("status", "unknown")}
        except httpx.HTTPError as exc:
            log.warning("get_message_status(%s) failed: %r", message_id, exc)
            return {"error": str(exc)}

    def _send(self, to_phone: str, body: str) -> WhatsAppSendResult:
        # Twilio requires "whatsapp:" prefix on numbers
        to_wa = f"whatsapp:{to_phone}" if not to_phone.startswith("whatsapp:") else to_phone

        try:
            resp = self._client.post(
                f"{self.BASE_URL}/{self._account_sid}/Messages.json",
                data={
                    "From": self._from_number,
                    "To": to_wa,
                    "Body": body,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            message_sid = data.get("sid")
            log.info(
                "Twilio WhatsApp sent to %s — sid=%s",
                to_phone,
                message_sid,
            )
            return WhatsAppSendResult(success=True, message_id=message_sid)
        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            log.error(
                "Twilio WhatsApp send failed (HTTP %s): %s",
                exc.response.status_code,
                error_body,
            )
            return WhatsAppSendResult(success=False, error=error_body)
        except httpx.HTTPError as exc:
            log.error("Twilio WhatsApp send failed (network): %r", exc)
            return WhatsAppSendResult(success=False, error=str(exc))


# ---------------------------------------------------------------------------
# Mock implementation — in-memory, for demo and tests
# ---------------------------------------------------------------------------


@dataclass
class _MockMessage:
    message_id: str
    to_phone: str
    kind: str  # "template" | "text"
    template_name: Optional[str]
    template_params: Dict[str, str]
    text: Optional[str]
    sent_at: datetime
    status: str = "sent"


class MockWhatsAppProvider:
    """Logs WhatsApp sends to console and keeps an in-memory ledger.

    Useful for the demo and unit tests. Access ``.sent_messages`` to inspect
    what the engine dispatched.
    """

    _global_messages: List[_MockMessage] = []

    def __init__(self) -> None:
        self.sent_messages: List[_MockMessage] = self.__class__._global_messages

    # -- protocol methods ---------------------------------------------------

    def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        template_params: Dict[str, str],
        language: str = "en",
    ) -> WhatsAppSendResult:
        msg_id = f"wamid.mock_{uuid4().hex[:12]}"
        msg = _MockMessage(
            message_id=msg_id,
            to_phone=to_phone,
            kind="template",
            template_name=template_name,
            template_params=template_params,
            text=None,
            sent_at=datetime.utcnow(),
        )
        self.sent_messages.append(msg)
        log.info(
            "[MOCK WhatsApp] template=%s to=%s params=%s -> %s",
            template_name,
            to_phone,
            template_params,
            msg_id,
        )
        return WhatsAppSendResult(success=True, message_id=msg_id)

    def send_text_message(self, to_phone: str, text: str) -> WhatsAppSendResult:
        msg_id = f"wamid.mock_{uuid4().hex[:12]}"
        msg = _MockMessage(
            message_id=msg_id,
            to_phone=to_phone,
            kind="text",
            template_name=None,
            template_params={},
            text=text,
            sent_at=datetime.utcnow(),
        )
        self.sent_messages.append(msg)
        log.info("[MOCK WhatsApp] text to=%s -> %s", to_phone, msg_id)
        return WhatsAppSendResult(success=True, message_id=msg_id)

    def get_message_status(self, message_id: str) -> Dict[str, Any]:
        for msg in self.sent_messages:
            if msg.message_id == message_id:
                return {"id": message_id, "status": msg.status}
        return {"id": message_id, "status": "unknown"}

    # -- test helpers -------------------------------------------------------

    @classmethod
    def reset_global_state(cls) -> None:
        cls._global_messages.clear()
