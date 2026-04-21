"""Tests for the Claude salary-slip extractor.

Force the deterministic provider via env so no live API call is made;
exercises the regex fallback that is also the safety net in production.
"""

from __future__ import annotations

import pytest

from app.models import CompensationBreakdown
from app.services.claude_salary_extractor import (
    extract_salary,
    _annualise,
    _grep_amount,
)


@pytest.fixture(autouse=True)
def _force_deterministic(monkeypatch):
    monkeypatch.setenv("AXIS_SALARY_EXTRACTOR", "deterministic")


SAMPLE_SLIP = """HDFC Bank Ltd.
Payslip for the month of Mar 2026
Employee: Priya Sharma   Emp ID: HDB-22019

Earnings                    Amount (INR)
Basic                       62,000
HRA                         24,800
Special Allowance           37,000
Conveyance                  1,600

Annual variable pay         2,22,000
"""


def test_extract_salary_deterministic_returns_breakdown():
    breakdown, source = extract_salary(SAMPLE_SLIP, source_filename="march.pdf")
    assert source == "deterministic"
    assert isinstance(breakdown, CompensationBreakdown)
    # Basic 62,000 / month → 7,44,000 / year
    assert breakdown.basic == 62000 * 12
    assert breakdown.hra == 24800 * 12
    assert breakdown.special_allowance == 37000 * 12
    assert breakdown.variable == 222000
    # CTC = sum of annualised earnings + variable
    assert breakdown.current_ctc and breakdown.current_ctc > 0
    assert breakdown.employer == "HDFC Bank Ltd."
    assert breakdown.pay_period and "Mar 2026" in breakdown.pay_period
    assert breakdown.source_filename == "march.pdf"
    assert breakdown.extraction_source == "deterministic"


def test_extract_salary_unparseable_returns_note():
    breakdown, source = extract_salary("not a slip\njust random words")
    assert source == "deterministic"
    assert breakdown.current_ctc is None
    assert breakdown.extraction_notes


def test_annualise_helper():
    assert _annualise(None) is None
    assert _annualise(50000) == 600000.0


def test_grep_amount_handles_indian_formatting():
    assert _grep_amount(r"basic", "Basic ₹62,000") == 62000.0
    assert _grep_amount(r"basic", "no match here") is None


def test_provider_env_override_to_claude_without_key_falls_back(monkeypatch):
    # Even if user sets claude, missing API key must NOT raise — we degrade.
    monkeypatch.setenv("AXIS_SALARY_EXTRACTOR", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    breakdown, source = extract_salary(SAMPLE_SLIP)
    assert source == "deterministic"
    assert breakdown.current_ctc is not None
