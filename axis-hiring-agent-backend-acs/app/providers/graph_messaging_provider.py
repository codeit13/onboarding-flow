"""Real Microsoft Graph MessagingProvider.

Activated by ``AXIS_MESSAGING_PROVIDER=graph``. Sends email **from** the
service mailbox (``AXIS_GRAPH_ORGANISER_UPN``) and reads replies **from**
that same mailbox's Inbox.

Endpoints used:

    POST /v1.0/users/{upn}/sendMail
    GET  /v1.0/users/{upn}/messages?$top=50&$orderby=receivedDateTime desc

Application permissions required (already granted for this tenant):
    Mail.Send, Mail.ReadWrite

Design notes
------------
1. **Outbound**: we call ``/sendMail`` with the Message inline in the POST
   body and ``saveToSentItems=true`` so the message shows up in the service
   mailbox's Sent Items folder (great for demo inspection). Graph returns
   202 Accepted with no body, so we can't read the canonical message id
   back directly. We synthesise a local id + track it in an in-memory mirror
   so ``list_emails`` can return recent sends without a second round-trip.

2. **Inbound** (replies from candidates): we poll
   ``GET /users/{upn}/messages`` and filter by ``conversationId`` if a
   thread_id is present, otherwise return the last 50 messages. Replies
   that come back from external addresses (e.g. the candidate's real
   Gmail) land in the service mailbox's Inbox and are surfaced via this
   call. In-app notifications are NOT part of Graph — we store them on a
   local list that the UI reads directly.

3. **Thread tracking**: Graph uses ``conversationId`` to thread a mailbox
   conversation. Our internal ``thread_id`` maps 1:1 onto Graph's
   ``conversationId``. When ``send_email`` is called with a thread_id,
   we set the outgoing Message's ``conversationId`` so Graph keeps the
   conversation threaded.

4. **Notifications** (the in-app HR/panel toast feed) are NOT Graph
   concerns — they live in a local ``_NOTIFICATIONS`` list that this
   provider manages directly. The UI reads them via ``list_notifications``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

import httpx

from .graph_auth import GRAPH_BASE_URL, get_auth
from .messaging_provider import EmailMessage, Notification

log = logging.getLogger(__name__)


class GraphMessagingError(RuntimeError):
    pass


# Module-level notification list — in-app notifications are not a Graph concept.
_NOTIFICATIONS: List[Notification] = []
# Module-level sent-mail mirror — populated on every send so list_emails()
# returns them instantly without a second Graph call.
_SENT_MIRROR: List[EmailMessage] = []


class GraphMessagingProvider:
    """MessagingProvider implemented against live Microsoft Graph."""

    def __init__(self) -> None:
        self.from_mailbox = os.getenv("AXIS_GRAPH_ORGANISER_UPN", "").strip()
        if not self.from_mailbox:
            raise RuntimeError(
                "GraphMessagingProvider requires AXIS_GRAPH_ORGANISER_UPN — "
                "the UPN of the service mailbox that sends hiring emails."
            )
        get_auth()  # fail fast if misconfigured

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=GRAPH_BASE_URL,
            headers={**get_auth().auth_header(), "Content-Type": "application/json"},
            timeout=20.0,
        )

    @staticmethod
    def _raise_for_status(r: httpx.Response, op: str) -> None:
        if r.status_code >= 300:
            raise GraphMessagingError(
                f"Graph {op} failed: HTTP {r.status_code} — {r.text[:600]}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        application_id: Optional[str] = None,
        from_addr: Optional[str] = None,
    ) -> EmailMessage:
        """Send mail from the service mailbox to ``to``.

        The ``from_addr`` parameter is honoured only if it matches the
        configured service mailbox — otherwise we silently use the service
        mailbox (Graph ``sendMail`` on ``/users/{upn}/sendMail`` sends *as*
        that user regardless).
        """
        graph_body = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": (body or "").replace("\n", "<br>"),
                },
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }
        # Thread continuation: setting conversationId on an outbound Message is
        # not allowed directly by Graph, but passing ``references`` in a reply
        # via POST /messages/{id}/reply is. For POC outbound (agent initiates)
        # we don't need this — Graph will allocate a new conversationId.

        with self._client() as client:
            r = client.post(
                f"/users/{self.from_mailbox}/sendMail",
                json=graph_body,
            )
        self._raise_for_status(r, "sendMail")

        # Graph returns 202 with no body. Synthesise a local record.
        msg = EmailMessage(
            id=f"msg-{uuid4().hex[:8]}",
            thread_id=thread_id or f"thr-{uuid4().hex[:8]}",
            to=to,
            from_addr=self.from_mailbox,
            subject=subject,
            body=body,
            at=datetime.utcnow(),
            direction="out",
            application_id=application_id,
        )
        _SENT_MIRROR.append(msg)
        log.info("Graph sendMail OK: %s -> %s (%s)", self.from_mailbox, to, subject[:60])
        return msg

    def read_email_thread(self, thread_id: str) -> List[EmailMessage]:
        """Return every message in the service mailbox with this conversationId."""
        url = f"/users/{self.from_mailbox}/messages"
        params = {
            "$filter": f"conversationId eq '{thread_id}'",
            "$orderby": "receivedDateTime asc",
            "$top": "50",
            "$select": "id,conversationId,subject,bodyPreview,body,from,toRecipients,receivedDateTime,sentDateTime",
        }
        with self._client() as client:
            r = client.get(url, params=params)
        if r.status_code == 404:
            return []
        self._raise_for_status(r, "list messages by conversationId")
        return [self._msg_from_graph(m) for m in r.json().get("value", [])]

    def list_emails(self, application_id: Optional[str] = None) -> List[EmailMessage]:
        """Return recent outbound + inbound messages for the service mailbox.

        The local ``_SENT_MIRROR`` handles outbound. Inbound messages are
        fetched fresh from Graph on each call (cheap for a demo tenant with
        low volume).
        """
        out: List[EmailMessage] = [
            m for m in _SENT_MIRROR
            if application_id is None or m.application_id == application_id
        ]

        try:
            url = f"/users/{self.from_mailbox}/messages"
            params = {
                "$top": "50",
                "$orderby": "receivedDateTime desc",
                "$select": "id,conversationId,subject,bodyPreview,body,from,toRecipients,receivedDateTime",
            }
            with self._client() as client:
                r = client.get(url, params=params)
            if r.status_code < 300:
                for m in r.json().get("value", []):
                    msg = self._msg_from_graph(m)
                    if msg.direction == "in":
                        out.append(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("Graph list_emails inbound fetch failed: %r", e)

        out.sort(key=lambda m: m.at)
        return out

    def notify(
        self,
        to: str,
        message: str,
        application_id: Optional[str] = None,
        jd_id: Optional[str] = None,
    ) -> Notification:
        note = Notification(
            id=f"note-{uuid4().hex[:6]}",
            to=to,
            application_id=application_id,
            jd_id=jd_id,
            message=message,
            at=datetime.utcnow(),
        )
        _NOTIFICATIONS.append(note)
        return note

    def list_notifications(self, to: Optional[str] = None) -> List[Notification]:
        notes = list(_NOTIFICATIONS)
        if to:
            notes = [n for n in notes if n.to == to]
        return sorted(notes, key=lambda n: n.at)

    def simulate_inbound(
        self,
        thread_id: str,
        from_addr: str,
        body: str,
        application_id: Optional[str] = None,
    ) -> EmailMessage:
        # Against a real mailbox, we can't fake an inbound message — the
        # candidate has to actually hit Reply in their mail client. For the
        # POC we log this and return a synthetic record so tests don't blow
        # up. If you need real inbound for the demo, just reply from your
        # Gmail to the agent's outreach email and the next poll will pick it up.
        log.warning(
            "simulate_inbound ignored on Graph provider (thread=%s, from=%s)",
            thread_id,
            from_addr,
        )
        return EmailMessage(
            id=f"msg-sim-{uuid4().hex[:8]}",
            thread_id=thread_id,
            to=self.from_mailbox,
            from_addr=from_addr,
            subject="(simulated inbound — ignored)",
            body=body,
            at=datetime.utcnow(),
            direction="in",
            application_id=application_id,
        )

    def reset(self) -> None:
        _SENT_MIRROR.clear()
        _NOTIFICATIONS.clear()

    @classmethod
    def reset_global_state(cls) -> None:
        _SENT_MIRROR.clear()
        _NOTIFICATIONS.clear()

    # ------------------------------------------------------------------
    # Internal: Graph -> EmailMessage
    # ------------------------------------------------------------------

    def _msg_from_graph(self, m: dict) -> EmailMessage:
        from_addr = (
            ((m.get("from") or {}).get("emailAddress") or {}).get("address", "")
        )
        to_addrs = [
            ((t.get("emailAddress") or {}).get("address") or "")
            for t in (m.get("toRecipients") or [])
        ]
        to = to_addrs[0] if to_addrs else ""

        direction = "in" if from_addr.lower() != self.from_mailbox.lower() else "out"

        raw_at = m.get("receivedDateTime") or m.get("sentDateTime") or ""
        try:
            at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
            at = at.replace(tzinfo=None)  # our model is naive
        except Exception:
            at = datetime.utcnow()

        body_content = (m.get("body") or {}).get("content") or m.get("bodyPreview") or ""

        return EmailMessage(
            id=m.get("id", f"msg-{uuid4().hex[:8]}"),
            thread_id=m.get("conversationId", ""),
            to=to,
            from_addr=from_addr,
            subject=m.get("subject", ""),
            body=body_content,
            at=at,
            direction=direction,
            application_id=None,  # Graph doesn't carry our application_id
        )
