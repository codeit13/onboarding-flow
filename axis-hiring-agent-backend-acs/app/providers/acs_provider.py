"""Azure Communication Services (ACS) Call Automation provider.

This is the boundary between the Axis hiring agent and the ACS Call
Automation SDK. The agent uses an ``AcsProvider`` to:

  1. Join a Microsoft Teams meeting on the candidate's behalf, using the
     meeting join URL produced by the existing Graph calendar provider.
  2. Play TTS audio (interview questions) into the call.
  3. Stream incoming candidate audio out via WebSocket so the rest of
     the system can transcribe it (Azure Speech / Whisper).
  4. End the call cleanly and surface the final transcript + recording.

We expose two implementations:

  ``MockAcsProvider``  — pure-Python in-memory simulation. No network. Used
                         in tests AND in the demo when the operator hasn't
                         provisioned an ACS resource. Generates a synthetic
                         transcript by alternating scripted "agent asks"
                         lines with a deterministic candidate response.

  ``AzureAcsProvider`` — wraps the real ``azure-communication-callautomation``
                         SDK. Lazy-imported so the codebase still loads
                         when the SDK isn't installed (e.g. in CI). Real
                         ACS hookup is gated behind ``AXIS_ACS_PROVIDER=azure``
                         and a connection string.

The factory in ``app.providers.__init__`` reads ``AXIS_ACS_PROVIDER`` and
returns the right concrete instance.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Protocol


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


@dataclass
class AcsCallSession:
    """A live (or just-finished) ACS Teams call session."""

    call_id: str
    application_id: str
    teams_join_url: str
    state: str = "joining"  # joining | live | ended | failed
    questions: List[str] = field(default_factory=list)
    asked: List[str] = field(default_factory=list)
    transcript_lines: List[Dict[str, str]] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    error: Optional[str] = None

    def to_public_dict(self) -> Dict:
        return {
            "call_id": self.call_id,
            "application_id": self.application_id,
            "teams_join_url": self.teams_join_url,
            "state": self.state,
            "questions_total": len(self.questions),
            "questions_asked": len(self.asked),
            "current_question": self.asked[-1] if self.asked else None,
            "transcript": list(self.transcript_lines),
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "error": self.error,
        }


class AcsProvider(Protocol):
    """Minimal ACS Call Automation surface the agent depends on."""

    def join_teams_meeting(
        self,
        *,
        application_id: str,
        teams_join_url: str,
        questions: List[str],
        on_update: Optional[Callable[[AcsCallSession], None]] = None,
    ) -> AcsCallSession:
        ...

    def get_session(self, call_id: str) -> Optional[AcsCallSession]:
        ...

    def end_call(self, call_id: str) -> Optional[AcsCallSession]:
        ...


# ---------------------------------------------------------------------------
# Mock provider — drives a simulated end-to-end interview in a background
# thread so the frontend can poll status / live transcript and feel a
# real call. Zero network. Zero Azure dependency.
# ---------------------------------------------------------------------------


_DEFAULT_CANDIDATE_RESPONSES = [
    (
        "Thanks for the warm welcome. In my last role I owned the Burgundy "
        "upgrade drive end-to-end — converted 71 of 280 mass-affluent "
        "customers in a 90-day push, which added about ₹84 crore in book "
        "value."
    ),
    (
        "I track cross-sell quality by the 6-month retention of the second "
        "product, not the day-one sale. If a customer mentions a goal — say "
        "a child's education — I match them with an SIP or an education loan."
    ),
    (
        "Last year I disagreed with my zonal head on shutting down our "
        "Saturday open-house. I pulled the data, showed 60% of Q2 Burgundy "
        "upgrades had their first meeting on a Saturday, and asked for one "
        "more quarter to prove it. The number held."
    ),
    (
        "On a suspected mis-selling complaint I pull the call recording and "
        "needs-analysis form first, loop in compliance same-day in writing, "
        "and call the customer myself. The priority is the customer, not "
        "saving the sale."
    ),
    (
        "I'm working on delegating analytics work — I tend to pull data "
        "myself because I trust my own SQL. I've been forcing myself to "
        "hand questions to my MIS analyst for three months now."
    ),
]


class MockAcsProvider:
    """Offline simulation of an ACS Teams call.

    Spawns a background thread that walks through the question list,
    appends synthetic transcript lines at a configurable cadence, and
    transitions through ``joining → live → ended``. The frontend polls
    ``get_session`` to see live progress, exactly as it would with the
    real ACS provider.
    """

    # Class-level store so the FastAPI process keeps state across requests.
    _sessions: Dict[str, AcsCallSession] = {}
    _lock = threading.Lock()

    # Per-question delay (seconds). Tests override to 0 for instant runs.
    QUESTION_DELAY_SEC = float(os.getenv("AXIS_ACS_MOCK_QUESTION_DELAY", "1.5"))

    @classmethod
    def reset_global_state(cls) -> None:
        with cls._lock:
            cls._sessions.clear()

    def join_teams_meeting(
        self,
        *,
        application_id: str,
        teams_join_url: str,
        questions: List[str],
        on_update: Optional[Callable[[AcsCallSession], None]] = None,
    ) -> AcsCallSession:
        call_id = f"acs-mock-{uuid.uuid4().hex[:8]}"
        session = AcsCallSession(
            call_id=call_id,
            application_id=application_id,
            teams_join_url=teams_join_url,
            questions=list(questions),
        )
        with self._lock:
            self._sessions[call_id] = session

        thread = threading.Thread(
            target=self._run_simulation,
            args=(session, on_update),
            daemon=True,
            name=f"acs-mock-{call_id}",
        )
        thread.start()
        return session

    def _run_simulation(
        self,
        session: AcsCallSession,
        on_update: Optional[Callable[[AcsCallSession], None]],
    ) -> None:
        try:
            # Phase 1: joining handshake
            self._sleep_short()
            with self._lock:
                session.state = "live"
                session.transcript_lines.append(
                    {
                        "speaker": "agent",
                        "text": (
                            "Hello, this is the Axis AI Interview Agent. "
                            "Thanks for joining the Round 1 interview. "
                            "I'll ask you a few questions — please answer "
                            "naturally, and take your time."
                        ),
                        "at": datetime.utcnow().isoformat(),
                    }
                )
            if on_update:
                on_update(session)

            # Phase 2: ask each question, capture a synthetic response
            for idx, q in enumerate(session.questions):
                self._sleep_short()
                with self._lock:
                    session.asked.append(q)
                    session.transcript_lines.append(
                        {
                            "speaker": "agent",
                            "text": q,
                            "at": datetime.utcnow().isoformat(),
                        }
                    )
                if on_update:
                    on_update(session)

                self._sleep_short()
                response = _DEFAULT_CANDIDATE_RESPONSES[
                    idx % len(_DEFAULT_CANDIDATE_RESPONSES)
                ]
                with self._lock:
                    session.transcript_lines.append(
                        {
                            "speaker": "candidate",
                            "text": response,
                            "at": datetime.utcnow().isoformat(),
                        }
                    )
                if on_update:
                    on_update(session)

            # Phase 3: wrap up
            self._sleep_short()
            with self._lock:
                session.transcript_lines.append(
                    {
                        "speaker": "agent",
                        "text": (
                            "Thank you for your time. Your responses have "
                            "been recorded and will be reviewed by the "
                            "hiring panel."
                        ),
                        "at": datetime.utcnow().isoformat(),
                    }
                )
                session.state = "ended"
                session.ended_at = datetime.utcnow()
            if on_update:
                on_update(session)

        except Exception as exc:  # noqa: BLE001
            with self._lock:
                session.state = "failed"
                session.error = repr(exc)
                session.ended_at = datetime.utcnow()
            if on_update:
                on_update(session)

    def _sleep_short(self) -> None:
        delay = self.QUESTION_DELAY_SEC
        if delay > 0:
            import time

            time.sleep(delay)

    def get_session(self, call_id: str) -> Optional[AcsCallSession]:
        with self._lock:
            return self._sessions.get(call_id)

    def end_call(self, call_id: str) -> Optional[AcsCallSession]:
        with self._lock:
            session = self._sessions.get(call_id)
            if session is None:
                return None
            if session.state not in ("ended", "failed"):
                session.state = "ended"
                session.ended_at = datetime.utcnow()
            return session


# ---------------------------------------------------------------------------
# Real Azure ACS provider — lazy-imports the SDK so the codebase still
# loads when the operator hasn't installed it. Hookup is intentionally
# minimal: real wiring lives behind ``AXIS_ACS_PROVIDER=azure`` and is
# expected to be wired up after the SDK + ACS resource are provisioned.
# ---------------------------------------------------------------------------


class AzureAcsProvider:
    """Thin wrapper around ``azure-communication-callautomation``.

    Methods raise ``RuntimeError`` until the SDK + connection string are
    in place. The Mock provider is the offline default; flip
    ``AXIS_ACS_PROVIDER=azure`` once the Azure resource is provisioned
    and the SDK installed.
    """

    def __init__(self) -> None:
        self._connection_string = os.getenv("AXIS_ACS_CONNECTION_STRING", "")
        self._base_url = os.getenv("AXIS_ACS_BASE_URL", "")
        if not self._connection_string:
            raise RuntimeError(
                "AXIS_ACS_CONNECTION_STRING is required for AzureAcsProvider"
            )
        if not self._base_url:
            raise RuntimeError(
                "AXIS_ACS_BASE_URL is required (public webhook callback URL)"
            )
        self._client = self._build_client()
        self._sessions: Dict[str, AcsCallSession] = {}
        self._lock = threading.Lock()

    def _build_client(self):
        try:
            from azure.communication.callautomation import (  # type: ignore
                CallAutomationClient,
            )
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "azure-communication-callautomation is not installed. "
                "Run: pip install azure-communication-callautomation"
            ) from exc
        return CallAutomationClient.from_connection_string(self._connection_string)

    def join_teams_meeting(
        self,
        *,
        application_id: str,
        teams_join_url: str,
        questions: List[str],
        on_update: Optional[Callable[[AcsCallSession], None]] = None,
    ) -> AcsCallSession:
        # Real implementation outline (left as a TODO so the offline mock
        # can ship today and the real call comes online when ACS is
        # provisioned):
        #
        #   1. Build TeamsMeetingLocator(meeting_link=teams_join_url)
        #   2. self._client.connect_call(call_locator=locator,
        #         callback_url=f"{self._base_url}/acs/webhook/call-events")
        #   3. Persist {call_connection_id -> AcsCallSession} so the
        #      webhook can resume per-call state.
        #   4. On CallConnected event → start_recognizing_media() to grab
        #      candidate speech, and play_media(text=q, ...) to TTS each
        #      question via Azure Speech.
        #   5. On RecognizeCompleted → append transcript line, advance
        #      to next question, fire on_update.
        #   6. On the last question → hang_up() and mark state="ended".
        raise NotImplementedError(
            "AzureAcsProvider.join_teams_meeting — real wiring is gated "
            "until the ACS resource is provisioned. Set "
            "AXIS_ACS_PROVIDER=mock to run the offline simulation."
        )

    def get_session(self, call_id: str) -> Optional[AcsCallSession]:
        with self._lock:
            return self._sessions.get(call_id)

    def end_call(self, call_id: str) -> Optional[AcsCallSession]:
        with self._lock:
            session = self._sessions.get(call_id)
        if session is None:
            return None
        # self._client.hang_up(call_connection_id, is_for_everyone=True)
        session.state = "ended"
        session.ended_at = datetime.utcnow()
        return session


__all__ = [
    "AcsCallSession",
    "AcsProvider",
    "MockAcsProvider",
    "AzureAcsProvider",
]
