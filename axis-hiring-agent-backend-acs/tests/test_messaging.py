"""Messaging provider + tool wrapper tests."""

import pytest

from app.models import Application
from app.providers import get_messaging_provider
from app.store import STORE
from app.tools import notify_hr_partner, notify_panel, read_email_thread, send_email
from app.tools.messaging import simulate_candidate_reply


def _seed_app() -> Application:
    app = Application(
        id="app-msg",
        candidate_id="EMP10234",
        job_id="job-590321",
        match_percent=88.0,
    )
    STORE.add_application(app)
    return app


class TestSendEmail:
    def test_records_outbound_email(self):
        msg = send_email(to="rohan.verma@axisbank.test", subject="Hello", body="Body")
        sent = get_messaging_provider().list_emails()
        assert any(m.id == msg.id and m.direction == "out" for m in sent)
        assert msg.thread_id.startswith("thr-")

    def test_reuses_thread_id(self):
        a = send_email(to="x@axisbank.test", subject="1", body="b")
        b = send_email(to="x@axisbank.test", subject="2", body="b", thread_id=a.thread_id)
        assert a.thread_id == b.thread_id


class TestReadEmailThread:
    def test_merges_inbound_and_outbound(self):
        out = send_email(to="rohan@axisbank.test", subject="Slot", body="pick one")
        simulate_candidate_reply(
            thread_id=out.thread_id,
            candidate_email="rohan@axisbank.test",
            body="I'll take slot 1",
        )
        thread = read_email_thread(out.thread_id)
        assert len(thread) == 2
        assert {m.direction for m in thread} == {"in", "out"}


class TestNotifyHrPartner:
    def test_appends_notification_and_audits_app(self):
        _seed_app()
        notify_hr_partner("app-msg", "R1 scheduled")
        notes = get_messaging_provider().list_notifications()
        # job-590321's HR partner is hr.bhopal@axisbank.test (or the graph
        # tenant equivalent if AXIS_CALENDAR_PROVIDER=graph). We just check
        # the notification carries the right application id.
        assert any(n.application_id == "app-msg" for n in notes)
        app = STORE.get_application("app-msg")
        # Note: backend agent log strings were renamed "HR partner" → "Business Partner"
        # per stakeholder feedback (the route + identifier hr_partner are unchanged).
        assert any("Notified Business Partner" in e.message for e in app.events)

    def test_missing_application_raises(self):
        with pytest.raises(LookupError):
            notify_hr_partner("nope", "hi")


class TestNotifyPanel:
    def test_fans_out_to_every_non_hr_panellist(self):
        ids = notify_panel("job-590321", "R2 scheduled for Rohan")
        # Bhopal panel is HR + HM + 2 interviewers — notify_panel skips the HR
        # role, so we should get 3 user_ids back.
        assert len(ids) == 3
        notes = get_messaging_provider().list_notifications()
        for uid in ids:
            assert any(n.to == uid for n in notes)

    def test_missing_jd_raises(self):
        with pytest.raises(LookupError):
            notify_panel("does-not-exist", "hi")
