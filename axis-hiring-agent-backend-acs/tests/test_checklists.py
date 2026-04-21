"""Phase 4/5 — Checklist tooling tests."""

import pytest

from app.models import Application, ChecklistItem
from app.store import STORE
from app.tools import (
    get_checklist,
    instantiate_checklist,
    is_checklist_satisfied,
    tick_checklist_item,
)
from app.tools.checklists import customise_checklist


def _seed_app() -> Application:
    app = Application(
        id="app-chk",
        candidate_id="EMP10234",
        job_id="job-590321",
        match_percent=88.0,
    )
    STORE.add_application(app)
    return app


class TestGetChecklist:
    def test_default_r1_pre_has_six_items(self):
        items = get_checklist("job-590321", "R1", "pre")
        assert len(items) == 6
        assert any("Teams meeting" in i.label for i in items)

    def test_default_r1_post_has_four_items(self):
        items = get_checklist("job-590321", "R1", "post")
        assert len(items) == 4

    def test_default_r2_pre_and_post_exist(self):
        assert len(get_checklist("job-590321", "R2", "pre")) == 6
        assert len(get_checklist("job-590321", "R2", "post")) == 4

    def test_customisation_is_merged_on_top_of_default(self):
        extra = [
            ChecklistItem(id="custom-1", label="Bhopal-specific compliance sign-off", blocking=True)
        ]
        customise_checklist("job-590321", "R1", "pre", extra)
        merged = get_checklist("job-590321", "R1", "pre")
        assert any(i.id == "custom-1" for i in merged)
        assert len(merged) == 7

    def test_missing_jd_raises(self):
        with pytest.raises(LookupError):
            get_checklist("does-not-exist", "R1", "pre")


class TestInstantiateAndTick:
    def test_instantiate_attaches_to_application(self):
        _seed_app()
        inst = instantiate_checklist("app-chk", "R1", "pre")
        assert inst.application_id == "app-chk"
        assert len(inst.items) == 6
        app = STORE.get_application("app-chk")
        assert len(app.checklists) == 1

    def test_reinstantiate_is_idempotent(self):
        _seed_app()
        instantiate_checklist("app-chk", "R1", "pre")
        instantiate_checklist("app-chk", "R1", "pre")
        app = STORE.get_application("app-chk")
        assert len([c for c in app.checklists if c.round == "R1" and c.phase == "pre"]) == 1

    def test_tick_marks_item_done_with_note(self):
        _seed_app()
        instantiate_checklist("app-chk", "R1", "pre")
        tick_checklist_item("app-chk", "R1", "pre", "pre-r1-1", note="Candidate replied")
        app = STORE.get_application("app-chk")
        inst = app.checklists[0]
        item = next(i for i in inst.items if i.id == "pre-r1-1")
        assert item.done is True
        assert item.note == "Candidate replied"

    def test_tick_unknown_item_raises(self):
        _seed_app()
        instantiate_checklist("app-chk", "R1", "pre")
        with pytest.raises(LookupError):
            tick_checklist_item("app-chk", "R1", "pre", "does-not-exist")


class TestIsSatisfied:
    def test_fresh_checklist_not_satisfied(self):
        _seed_app()
        instantiate_checklist("app-chk", "R1", "pre")
        assert is_checklist_satisfied("app-chk", "R1", "pre") is False

    def test_blocking_only_mode(self):
        _seed_app()
        instantiate_checklist("app-chk", "R1", "pre")
        # Tick only blocking items (pre-r1-1..4), leave advisory (5, 6) untouched.
        for i in range(1, 5):
            tick_checklist_item("app-chk", "R1", "pre", f"pre-r1-{i}")
        assert is_checklist_satisfied("app-chk", "R1", "pre", blocking_only=True) is True
        assert is_checklist_satisfied("app-chk", "R1", "pre", blocking_only=False) is False

    def test_all_ticked_is_satisfied(self):
        _seed_app()
        instantiate_checklist("app-chk", "R1", "pre")
        for i in range(1, 7):
            tick_checklist_item("app-chk", "R1", "pre", f"pre-r1-{i}")
        assert is_checklist_satisfied("app-chk", "R1", "pre", blocking_only=False) is True
