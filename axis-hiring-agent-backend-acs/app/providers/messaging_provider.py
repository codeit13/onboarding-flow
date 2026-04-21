"""MessagingProvider — abstract contract + in-memory mock.

Models the outbound + inbound email channel the agent uses to talk to
candidates (outreach, reschedule, regret). Mirrors the Graph Mail API surface.

The mock keeps everything in-memory so the demo + tests are deterministic.
The Graph provider lives next door in ``graph_messaging_provider``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Protocol
from uuid import uuid4


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EmailMessage:
    id: str
    thread_id: str
    to: str
    from_addr: str
    subject: str
    body: str
    at: datetime
    direction: str  # "out" or "in"
    application_id: Optional[str] = None


@dataclass
class Notification:
    id: str
    to: str                      # role keyword ("hr_partner", "panel") or user_id
    application_id: Optional[str]
    jd_id: Optional[str]
    message: str
    at: datetime


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


class MessagingProvider(Protocol):
    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        application_id: Optional[str] = None,
        from_addr: Optional[str] = None,
    ) -> EmailMessage: ...

    def read_email_thread(self, thread_id: str) -> List[EmailMessage]: ...

    def list_emails(self, application_id: Optional[str] = None) -> List[EmailMessage]: ...

    def notify(
        self,
        to: str,
        message: str,
        application_id: Optional[str] = None,
        jd_id: Optional[str] = None,
    ) -> Notification: ...

    def list_notifications(self, to: Optional[str] = None) -> List[Notification]: ...

    def simulate_inbound(
        self,
        thread_id: str,
        from_addr: str,
        body: str,
        application_id: Optional[str] = None,
    ) -> EmailMessage: ...

    def reset(self) -> None: ...


# ---------------------------------------------------------------------------
# Mock implementation
# ---------------------------------------------------------------------------


_SENT: List[EmailMessage] = []
_INBOX: List[EmailMessage] = []
_NOTIFICATIONS: List[Notification] = []


class MockMessagingProvider:
    SERVICE_MAILBOX = "axis-hiring-agent@axisbank.test"

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        application_id: Optional[str] = None,
        from_addr: Optional[str] = None,
    ) -> EmailMessage:
        msg = EmailMessage(
            id=f"msg-{uuid4().hex[:8]}",
            thread_id=thread_id or f"thr-{uuid4().hex[:8]}",
            to=to,
            from_addr=from_addr or self.SERVICE_MAILBOX,
            subject=subject,
            body=body,
            at=datetime.utcnow(),
            direction="out",
            application_id=application_id,
        )
        _SENT.append(msg)
        return msg

    def read_email_thread(self, thread_id: str) -> List[EmailMessage]:
        return sorted(
            [m for m in _SENT + _INBOX if m.thread_id == thread_id],
            key=lambda m: m.at,
        )

    def list_emails(self, application_id: Optional[str] = None) -> List[EmailMessage]:
        msgs = _SENT + _INBOX
        if application_id:
            msgs = [m for m in msgs if m.application_id == application_id]
        return sorted(msgs, key=lambda m: m.at)

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
        msg = EmailMessage(
            id=f"msg-{uuid4().hex[:8]}",
            thread_id=thread_id,
            to=self.SERVICE_MAILBOX,
            from_addr=from_addr,
            subject="Re: Interview slot",
            body=body,
            at=datetime.utcnow(),
            direction="in",
            application_id=application_id,
        )
        _INBOX.append(msg)
        return msg

    def reset(self) -> None:
        _SENT.clear()
        _INBOX.clear()
        _NOTIFICATIONS.clear()

    @classmethod
    def reset_global_state(cls) -> None:
        _SENT.clear()
        _INBOX.clear()
        _NOTIFICATIONS.clear()
