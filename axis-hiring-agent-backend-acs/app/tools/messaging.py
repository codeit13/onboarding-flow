"""Messaging tools — thin wrappers around the active MessagingProvider.

Also provides the higher-level ``notify_hr_partner`` and ``notify_panel``
helpers that the orchestrator uses: these bundle a notification + an audit
event on the application.
"""

from __future__ import annotations

from typing import List, Optional

from ..providers import get_messaging_provider
from ..providers.messaging_provider import EmailMessage, Notification
from ..store import STORE


def send_email(
    to: str,
    subject: str,
    body: str,
    thread_id: Optional[str] = None,
    application_id: Optional[str] = None,
    from_addr: Optional[str] = None,
) -> EmailMessage:
    return get_messaging_provider().send_email(
        to=to,
        subject=subject,
        body=body,
        thread_id=thread_id,
        application_id=application_id,
        from_addr=from_addr,
    )


def read_email_thread(thread_id: str) -> List[EmailMessage]:
    return get_messaging_provider().read_email_thread(thread_id)


def list_emails(application_id: Optional[str] = None) -> List[EmailMessage]:
    return get_messaging_provider().list_emails(application_id)


# ---------------------------------------------------------------------------
# In-app notification fan-out
# ---------------------------------------------------------------------------


def notify_hr_partner(application_id: str, message: str) -> Notification:
    app = STORE.get_application(application_id)
    if not app:
        raise LookupError(f"No application for id={application_id!r}")
    job = STORE.get_job(app.job_id)
    note = get_messaging_provider().notify(
        to=job.hr_partner_id if job else "hr_partner",
        message=message,
        application_id=application_id,
        jd_id=app.job_id,
    )
    app.log("agent", f"Notified Business Partner: {message}")
    return note


def notify_panel(jd_id: str, message: str, application_id: Optional[str] = None) -> List[str]:
    job = STORE.get_job(jd_id)
    if not job:
        raise LookupError(f"No JD for id={jd_id!r}")
    provider = get_messaging_provider()
    user_ids: List[str] = []
    for p in job.panel:
        if p.role == "hr_partner":
            continue
        provider.notify(
            to=p.user_id,
            message=message,
            application_id=application_id,
            jd_id=jd_id,
        )
        user_ids.append(p.user_id)
    return user_ids


def list_notifications(to: Optional[str] = None) -> List[Notification]:
    return get_messaging_provider().list_notifications(to)


def simulate_candidate_reply(
    thread_id: str,
    candidate_email: str,
    body: str,
    application_id: Optional[str] = None,
) -> EmailMessage:
    """Test helper — drop an inbound reply into the provider inbox."""
    return get_messaging_provider().simulate_inbound(
        thread_id=thread_id,
        from_addr=candidate_email,
        body=body,
        application_id=application_id,
    )
