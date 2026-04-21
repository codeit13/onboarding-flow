"""In-memory store for the POC.

Replace with Postgres + SQLAlchemy when we move past the demo. The tools talk
only to this module, so swapping the backing store is a one-file change.

Candidate pools are persisted to a JSON file so bulk-screening batches
survive backend restarts (uvicorn --reload, etc.).
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .models import Application, Candidate, CandidatePool, Job, Panel
from .models.engagement import EngagementJourney

log = logging.getLogger(__name__)

# File-based persistence for candidate pools
_POOLS_FILE = Path(__file__).resolve().parent.parent / "data" / "candidate_pools.json"

# File-based persistence for live applications (+candidates, +folders, +panels).
# Uvicorn's --reload restarts the process on every code edit, which wipes
# in-memory state. During a live demo that means any in-flight candidate's
# application disappears mid-flow (R1/R2/offer/onboarding). Persist these so
# the demo survives hot reloads.
_APPS_FILE = Path(__file__).resolve().parent.parent / "data" / "applications.json"


class Store:
    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self.candidates: Dict[str, Candidate] = {}
        self.applications: Dict[str, Application] = {}
        self.folders: Dict[str, List[str]] = {}  # folder_path -> list of application_ids
        self.panels: Dict[str, Panel] = {}
        self.candidate_pools: Dict[str, CandidatePool] = {}
        self.engagement_journeys: Dict[str, EngagementJourney] = {}
        # Debounced-write state: _save_apps() is called on every mutation
        # (add_candidate, add_application, save_application, panel CRUD,
        # folder moves). Without debouncing, bulk operations like screening
        # 6+ CVs in parallel trigger 30-50 full-state JSON dumps and stall
        # the request. Instead we mark dirty, schedule a single flush ~500ms
        # later, and coalesce all concurrent writes into it. atexit flushes
        # any pending dirty state on shutdown.
        self._apps_dirty = False
        self._apps_flush_timer: Optional[threading.Timer] = None
        self._apps_lock = threading.Lock()
        # Same debounce pattern for candidate_pools — bulk screening updates
        # each row through several status transitions (parsed → scoring →
        # done) and writes the entire pool JSON every time. Coalesce.
        self._pools_dirty = False
        self._pools_flush_timer: Optional[threading.Timer] = None
        self._pools_lock = threading.Lock()

    # ----- jobs -----
    def add_job(self, job: Job) -> None:
        self.jobs[job.id] = job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def list_jobs(self) -> List[Job]:
        return list(self.jobs.values())

    # ----- candidates -----
    def add_candidate(self, c: Candidate) -> None:
        self.candidates[c.id] = c
        self._save_apps()

    def get_candidate(self, candidate_id: str) -> Optional[Candidate]:
        return self.candidates.get(candidate_id)

    # ----- applications (persisted so --reload doesn't wipe the demo) -----
    def _save_apps(self) -> None:
        """Debounced snapshot writer.

        Marks the state as dirty and schedules a single background flush
        ~500ms later. Concurrent mutations coalesce into the same flush —
        so a batch of 50 mutations during bulk screening still produces
        exactly one (or two) disk writes instead of 50.
        """
        with self._apps_lock:
            self._apps_dirty = True
            if self._apps_flush_timer is None or not self._apps_flush_timer.is_alive():
                self._apps_flush_timer = threading.Timer(0.5, self._flush_apps)
                self._apps_flush_timer.daemon = True
                self._apps_flush_timer.start()

    def _flush_apps(self) -> None:
        """Actually write the snapshot to disk (called by the debounce timer)."""
        with self._apps_lock:
            if not self._apps_dirty:
                return
            self._apps_dirty = False
            # Snapshot references while holding the lock so we don't see
            # partial writes from other threads during serialization.
            apps = dict(self.applications)
            cands = dict(self.candidates)
            folders = {k: list(v) for k, v in self.folders.items()}
            panels = dict(self.panels)
        try:
            _APPS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "applications": {aid: a.model_dump(mode="json") for aid, a in apps.items()},
                "candidates":   {cid: c.model_dump(mode="json") for cid, c in cands.items()},
                "folders":      folders,
                "panels":       {pid: p.model_dump(mode="json") for pid, p in panels.items()},
            }
            _APPS_FILE.write_text(json.dumps(data, indent=2, default=str))
        except Exception as exc:
            log.warning("Failed to save applications snapshot: %s", exc)

    def _load_apps(self) -> None:
        if not _APPS_FILE.exists():
            return
        try:
            data = json.loads(_APPS_FILE.read_text())
            for aid, raw in data.get("applications", {}).items():
                self.applications[aid] = Application.model_validate(raw)
            for cid, raw in data.get("candidates", {}).items():
                self.candidates[cid] = Candidate.model_validate(raw)
            for k, v in data.get("folders", {}).items():
                self.folders[k] = list(v)
            for pid, raw in data.get("panels", {}).items():
                self.panels[pid] = Panel.model_validate(raw)
            log.info(
                "Loaded %d applications, %d candidates, %d panels from disk",
                len(self.applications), len(self.candidates), len(self.panels),
            )
        except Exception as exc:
            log.warning("Failed to load applications snapshot: %s", exc)

    def add_application(self, app: Application) -> None:
        self.applications[app.id] = app
        self._save_apps()

    def save_application(self, app: Application) -> None:
        """Persist an existing application after mutation (log/stage/slot update)."""
        self.applications[app.id] = app
        self._save_apps()

    def get_application(self, app_id: str) -> Optional[Application]:
        return self.applications.get(app_id)

    def list_applications(self) -> List[Application]:
        return list(self.applications.values())

    # ----- folders (CV file routing) -----
    def move_to_folder(self, application_id: str, folder: str) -> None:
        # Remove from all other folders first (single source of truth).
        for existing, ids in self.folders.items():
            if application_id in ids:
                ids.remove(application_id)
        self.folders.setdefault(folder, []).append(application_id)
        self._save_apps()

    def folder_contents(self, folder: str) -> List[str]:
        return list(self.folders.get(folder, []))

    # ----- panels (DESIGN-001) -----
    def add_panel(self, p: Panel) -> None:
        self.panels[p.id] = p
        self._save_apps()

    def get_panel(self, panel_id: str) -> Optional[Panel]:
        return self.panels.get(panel_id)

    def list_panels(self) -> List[Panel]:
        return list(self.panels.values())

    def delete_panel(self, panel_id: str) -> bool:
        removed = self.panels.pop(panel_id, None) is not None
        if removed:
            self._save_apps()
        return removed

    # ----- candidate pools (bulk screening) — persisted to JSON -----
    def _save_pools(self) -> None:
        """Debounced snapshot writer for candidate pools.

        Same pattern as _save_apps — coalesce concurrent row-status writes
        during bulk screening into at most one disk flush per 500ms.
        """
        with self._pools_lock:
            self._pools_dirty = True
            if self._pools_flush_timer is None or not self._pools_flush_timer.is_alive():
                self._pools_flush_timer = threading.Timer(0.5, self._flush_pools)
                self._pools_flush_timer.daemon = True
                self._pools_flush_timer.start()

    def _flush_pools(self) -> None:
        with self._pools_lock:
            if not self._pools_dirty:
                return
            self._pools_dirty = False
            pools = dict(self.candidate_pools)
        try:
            _POOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {pid: pool.model_dump(mode="json") for pid, pool in pools.items()}
            _POOLS_FILE.write_text(json.dumps(data, indent=2, default=str))
        except Exception as exc:
            log.warning("Failed to save candidate pools: %s", exc)

    def _load_pools(self) -> None:
        """Load candidate pools from disk on startup."""
        if not _POOLS_FILE.exists():
            return
        try:
            data = json.loads(_POOLS_FILE.read_text())
            for pid, raw in data.items():
                self.candidate_pools[pid] = CandidatePool.model_validate(raw)
            log.info("Loaded %d candidate pools from disk", len(self.candidate_pools))
        except Exception as exc:
            log.warning("Failed to load candidate pools: %s", exc)

    def add_candidate_pool(self, pool: CandidatePool) -> None:
        self.candidate_pools[pool.id] = pool
        self._save_pools()

    def get_candidate_pool(self, pool_id: str) -> Optional[CandidatePool]:
        return self.candidate_pools.get(pool_id)

    def list_candidate_pools(self) -> List[CandidatePool]:
        return list(self.candidate_pools.values())

    def save_candidate_pool(self, pool: CandidatePool) -> None:
        """Update and persist a pool (called after background processing updates rows)."""
        self.candidate_pools[pool.id] = pool
        self._save_pools()

    # ----- engagement journeys — persisted to JSON -----
    _ENGAGEMENTS_FILE = Path(__file__).resolve().parent.parent / "data" / "engagement_journeys.json"

    def _save_engagements(self) -> None:
        try:
            self._ENGAGEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {eid: ej.model_dump(mode="json") for eid, ej in self.engagement_journeys.items()}
            self._ENGAGEMENTS_FILE.write_text(json.dumps(data, indent=2, default=str))
        except Exception as exc:
            log.warning("Failed to save engagement journeys: %s", exc)

    def _load_engagements(self) -> None:
        if not self._ENGAGEMENTS_FILE.exists():
            return
        try:
            data = json.loads(self._ENGAGEMENTS_FILE.read_text())
            for eid, raw in data.items():
                self.engagement_journeys[eid] = EngagementJourney.model_validate(raw)
            log.info("Loaded %d engagement journeys from disk", len(self.engagement_journeys))
        except Exception as exc:
            log.warning("Failed to load engagement journeys: %s", exc)

    def add_engagement_journey(self, journey: EngagementJourney) -> None:
        self.engagement_journeys[journey.id] = journey
        self._save_engagements()

    def get_engagement_journey(self, journey_id: str) -> Optional[EngagementJourney]:
        return self.engagement_journeys.get(journey_id)

    def get_engagement_journey_by_application(self, app_id: str) -> Optional[EngagementJourney]:
        for j in self.engagement_journeys.values():
            if j.application_id == app_id:
                return j
        return None

    def list_engagement_journeys(self) -> List[EngagementJourney]:
        return list(self.engagement_journeys.values())

    def save_engagement_journey(self, journey: EngagementJourney) -> None:
        self.engagement_journeys[journey.id] = journey
        self._save_engagements()

    def delete_engagement_journey(self, journey_id: str) -> bool:
        """Remove a journey (e.g. orphaned after its application was wiped)."""
        if journey_id in self.engagement_journeys:
            del self.engagement_journeys[journey_id]
            self._save_engagements()
            return True
        return False

    def reset(self) -> None:
        # Cancel any pending debounced flush so we don't write stale state
        # back to disk after the wipe.
        with self._apps_lock:
            self._apps_dirty = False
            if self._apps_flush_timer is not None:
                self._apps_flush_timer.cancel()
                self._apps_flush_timer = None
        self.jobs.clear()
        self.candidates.clear()
        self.applications.clear()
        self.folders.clear()
        self.panels.clear()
        if _APPS_FILE.exists():
            try:
                _APPS_FILE.unlink()
            except Exception as exc:
                log.warning("Failed to remove applications snapshot file: %s", exc)
        # Engagement journeys are tied to applications — wipe them too, and
        # remove their on-disk file so they don't resurface as orphans on the
        # Onboarding Dashboard after restart.
        self.engagement_journeys.clear()
        if self._ENGAGEMENTS_FILE.exists():
            try:
                self._ENGAGEMENTS_FILE.unlink()
            except Exception as exc:
                log.warning("Failed to remove engagement journeys file: %s", exc)
        # NOTE: candidate_pools are NOT cleared on reset — they are
        # independently managed bulk-screening data persisted to disk.
        # They are only cleared explicitly via reset_candidate_pools().

    def reset_candidate_pools(self) -> None:
        """Explicitly clear all candidate pools (for wipe-only scenarios)."""
        self.candidate_pools.clear()
        if _POOLS_FILE.exists():
            _POOLS_FILE.unlink()


# Singleton for the running process. Tests reset this between cases.
STORE = Store()
STORE._load_pools()  # Restore any pools from previous runs
STORE._load_engagements()  # Restore engagement journeys from previous runs
STORE._load_apps()  # Restore applications/candidates/folders/panels so --reload doesn't wipe the demo


# Ensure any pending debounced writes are flushed on process exit — so a
# mutation that arrives right before uvicorn --reload kills the worker
# isn't lost.
def _flush_on_exit() -> None:
    try:
        if STORE._apps_flush_timer is not None:
            STORE._apps_flush_timer.cancel()
        STORE._flush_apps()
    except Exception as exc:
        log.warning("Failed to flush applications snapshot on exit: %s", exc)
    try:
        if STORE._pools_flush_timer is not None:
            STORE._pools_flush_timer.cancel()
        STORE._flush_pools()
    except Exception as exc:
        log.warning("Failed to flush candidate pools snapshot on exit: %s", exc)


atexit.register(_flush_on_exit)
