"""Inbound mail poller for the external candidate flow.

A daemon thread that periodically reads the Business Partner's mailbox via the
Graph messaging provider and feeds any new inbound messages into
``inbox_parser.handle_external_reply``. That entry point handles the
application lookup, slot extraction, and orchestrator hand-off.

Why a poller (and not webhooks)
-------------------------------
Microsoft Graph supports change notifications, but standing up an
HTTPS-reachable subscription endpoint is overkill for a POC running on a
developer's laptop. Polling every ``POLL_INTERVAL_SEC`` seconds is good
enough for a live demo and keeps the surface area tiny.

Idempotency
-----------
We dedupe on Graph message id in an in-memory ``_seen`` set. Restarting
the process re-processes the last 50 messages, but ``handle_external_reply``
is itself idempotent — once a slot is selected, the orchestrator's
``on_candidate_confirm_slot`` no-ops on a second confirmation because the
application has already moved past WAITING_CANDIDATE.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional, Set

from ..providers import get_messaging_provider
from .inbox_parser import handle_external_reply

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = float(os.getenv("AXIS_INBOX_POLL_SEC", "20"))


_seen: Set[str] = set()
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _poll_once() -> int:
    """One pass over the Business Partner's mailbox. Returns count of new messages
    that were dispatched to the parser (whether or not they advanced an app)."""
    provider = get_messaging_provider()
    list_emails = getattr(provider, "list_emails", None)
    if list_emails is None:
        return 0

    try:
        emails = list_emails()
    except Exception as exc:  # noqa: BLE001
        log.warning("inbox poller: list_emails failed: %r", exc)
        return 0

    dispatched = 0
    for msg in emails:
        if getattr(msg, "direction", "out") != "in":
            continue
        msg_id = getattr(msg, "id", None)
        if not msg_id or msg_id in _seen:
            continue
        _seen.add(msg_id)
        sender = getattr(msg, "from_addr", "") or ""
        body = getattr(msg, "body", "") or ""
        try:
            advanced = handle_external_reply(sender_email=sender, body_text=body)
            log.info(
                "inbox poller: dispatched msg %s from %s (advanced=%s)",
                msg_id, sender, advanced,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "inbox poller: handle_external_reply failed for %s: %r",
                msg_id, exc,
            )
        dispatched += 1
    return dispatched


def _loop() -> None:
    log.info("inbox poller: starting (interval=%ss)", POLL_INTERVAL_SEC)
    while not _stop_event.is_set():
        try:
            _poll_once()
        except Exception as exc:  # noqa: BLE001
            log.warning("inbox poller: unhandled error in poll loop: %r", exc)
        _stop_event.wait(POLL_INTERVAL_SEC)


def start_inbox_poller() -> None:
    """Idempotent — safe to call from FastAPI startup."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, name="inbox-poller", daemon=True)
    _thread.start()


def stop_inbox_poller() -> None:
    _stop_event.set()
