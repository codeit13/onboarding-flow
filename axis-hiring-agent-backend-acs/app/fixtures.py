"""Seed data for tests and the demo.

Production-grade demo dataset: 8 jobs across multiple Retail Banking
functions and 22 internal candidates with varied skill profiles, so the
HR kanban, Thrive employee view, and Panel queue all have meaningful
density without anything looking copy-pasted.

Live-demo override
------------------
When ``AXIS_CALENDAR_PROVIDER=graph`` is set (i.e. we're talking to real
Microsoft Graph), the synthetic ``@axisbank.test`` panel emails are
swapped at seed time for the four real mailboxes that exist in the
``Xebia192.onmicrosoft.com`` trial tenant. That lets the orchestrator's
``find_common_slots`` and ``create_teams_meeting`` calls succeed against
real users instead of failing with HTTP 404 "user not found".

The override is contained to ``seed_jobs`` so test fixtures (which run
in mock mode) keep their original synthetic panels and existing
assertions on ``sk.hm@axisbank.test`` etc. continue to pass unchanged.
"""

from __future__ import annotations

import os

from uuid import uuid4

from .models import Candidate, Job, Panel, PanelMember, Profile
from .services import taxonomy
from .store import STORE


# ---------------------------------------------------------------------------
# Axis taxonomy bridge
# ---------------------------------------------------------------------------
#
# Today's product feedback (2026-04-07) is to use ONLY the official Axis
# Bank role + skill taxonomy in the demo. This helper takes a real
# ``role_id`` from JOB_ROLES.csv and returns the (description,
# required_skills, function) tuple the seed Job should use, with a safe
# fallback if the CSV is missing in a stripped-down test runner.

def _from_taxonomy(
    role_id: str,
    *,
    fallback_skills: list[str],
    fallback_description: str = "",
    fallback_function: str = "Retail Banking",
    skill_limit: int = 8,
) -> tuple[str, list[str], str]:
    role = taxonomy.get_role_by_id(role_id)
    if role is None:
        return fallback_description, fallback_skills, fallback_function
    desc = role.role_summary or role.description[:600] or fallback_description
    skills = list(role.skills[:skill_limit]) or fallback_skills
    function = role.department or fallback_function
    return desc, skills, function


# ---------------------------------------------------------------------------
# Real tenant users (Xebia192.onmicrosoft.com) — only used in graph mode
# ---------------------------------------------------------------------------
#
# These four UPNs are the actual mailboxes in the M365 Business Basic
# trial tenant we use for the live demo. They get substituted into every
# panel at seed time when AXIS_CALENDAR_PROVIDER=graph.
#
# To add or rename real tenant users, update this block — it's the single
# source of truth for "who can the agent actually book meetings with".

GRAPH_TENANT_HR = PanelMember(
    user_id="meera.nair@Xebia192.onmicrosoft.com",
    name="Meera Nair",
    role="hr_partner",
)
GRAPH_TENANT_HM = PanelMember(
    user_id="suresh.kumar@Xebia192.onmicrosoft.com",
    name="Suresh Kumar",
    role="hiring_manager",
)
GRAPH_TENANT_INT_1 = PanelMember(
    user_id="SiddharthGoyal@Xebia192.onmicrosoft.com",
    name="Siddharth Goyal",
    role="interviewer",
)

# Synthetic ("stub") panel members used in graph mode alongside the real
# tenant mailboxes. These have plausible names but `@stub.local` UPNs so
# the GraphCalendarProvider can recognise them, skip the real Graph call,
# and treat them as "always free" weekday business hours. Each panel in
# graph mode is composed of [Suresh (real)] + 1-2 distinct stubs so the
# HR approval card shows visually distinct rosters per panel (BUG-008).
GRAPH_STUB_RAJESH = PanelMember(
    user_id="rajesh.menon@stub.local",
    name="Rajesh Menon",
    role="interviewer",
)
GRAPH_STUB_PRIYA = PanelMember(
    user_id="priya.shah@stub.local",
    name="Priya Shah",
    role="interviewer",
)
GRAPH_STUB_VIKRAM = PanelMember(
    user_id="vikram.nair@stub.local",
    name="Vikram Nair",
    role="hiring_manager",
)
GRAPH_STUB_ANANYA = PanelMember(
    user_id="ananya.iyer@stub.local",
    name="Ananya Iyer",
    role="interviewer",
)
GRAPH_STUB_KARTHIK = PanelMember(
    user_id="karthik.reddy@stub.local",
    name="Karthik Reddy",
    role="hiring_manager",
)
# NOTE: rohan.desai@Xebia192.onmicrosoft.com is the *candidate* in live mode,
# not a panel member. See _graph_candidate_email() below.
GRAPH_TENANT_CANDIDATE_UPN = "rohan.desai@Xebia192.onmicrosoft.com"
GRAPH_TENANT_CANDIDATE_NAME = "Rohan Desai"


def _use_graph_panels() -> bool:
    """True when we should swap synthetic panels for real tenant mailboxes."""
    return os.getenv("AXIS_CALENDAR_PROVIDER", "mock").strip().lower() == "graph"


def _real_tenant_panel() -> list[PanelMember]:
    """Return the real-tenant panel used in live graph mode.

    3 members: Business Partner (Meera) + Hiring Manager (Suresh) + Interviewer
    (Siddharth). Rohan Desai is NOT on this panel — he's the candidate.
    All three must vote before the orchestrator finalises the R2 decision.
    """
    return [GRAPH_TENANT_HR, GRAPH_TENANT_HM, GRAPH_TENANT_INT_1]


# ---------------------------------------------------------------------------
# Skill catalogue (kept inline so the file is one self-contained source)
# ---------------------------------------------------------------------------

BDM_REQUIRED_SKILLS = [
    "corporate salary acquisition",
    "relationship management",
    "portfolio sales",
    "stakeholder management",
    "KYC compliance",
    "CASA cross-sell",
]

BRANCH_MANAGER_SKILLS = [
    "branch operations",
    "team leadership",
    "P&L ownership",
    "audit & compliance",
    "customer experience",
    "CASA cross-sell",
]

WEALTH_RM_SKILLS = [
    "HNI relationship management",
    "portfolio advisory",
    "mutual funds",
    "AIF & PMS",
    "KYC compliance",
    "client acquisition",
]

CREDIT_ANALYST_SKILLS = [
    "credit underwriting",
    "financial statement analysis",
    "risk assessment",
    "RBI compliance",
    "MS Excel modelling",
    "secured lending",
]

OPS_MANAGER_SKILLS = [
    "branch operations",
    "audit & compliance",
    "team leadership",
    "process improvement",
    "KYC compliance",
    "vendor management",
]

DIGITAL_PRODUCT_SKILLS = [
    "product management",
    "user research",
    "analytics SQL",
    "stakeholder management",
    "agile delivery",
    "mobile banking",
]


# ---------------------------------------------------------------------------
# Synthetic panel members (used in mock mode and tests)
# ---------------------------------------------------------------------------

# BDM Bhopal
HR_BHOPAL = PanelMember(user_id="hr.bhopal@axisbank.test", name="Neha Sharma", role="hr_partner")
HM_BHOPAL = PanelMember(user_id="sk.hm@axisbank.test", name="Suresh Kapoor", role="hiring_manager")
INT_BHOPAL_1 = PanelMember(user_id="rv.int@axisbank.test", name="Rajesh Verma", role="interviewer")
INT_BHOPAL_2 = PanelMember(user_id="pm.int@axisbank.test", name="Priya Menon", role="interviewer")

# Branch Manager Pune
HR_PUNE = PanelMember(user_id="hr.pune@axisbank.test", name="Sanjay Joshi", role="hr_partner")
HM_PUNE = PanelMember(user_id="ag.hm@axisbank.test", name="Anita Ghosh", role="hiring_manager")
INT_PUNE_1 = PanelMember(user_id="rk.int@axisbank.test", name="Ravi Kulkarni", role="interviewer")

# Wealth RM Bengaluru
HR_BLR = PanelMember(user_id="hr.blr@axisbank.test", name="Divya Rao", role="hr_partner")
HM_BLR = PanelMember(user_id="kn.hm@axisbank.test", name="Kiran Nathan", role="hiring_manager")
INT_BLR_1 = PanelMember(user_id="ah.int@axisbank.test", name="Arjun Hegde", role="interviewer")
INT_BLR_2 = PanelMember(user_id="rs.int@axisbank.test", name="Radhika Subramanian", role="interviewer")

# Credit Analyst Mumbai
HR_MUM = PanelMember(user_id="hr.mum@axisbank.test", name="Farhan Sheikh", role="hr_partner")
HM_MUM = PanelMember(user_id="np.hm@axisbank.test", name="Nikhil Pai", role="hiring_manager")
INT_MUM_1 = PanelMember(user_id="ss.int@axisbank.test", name="Shilpa Sawant", role="interviewer")

# Ops Manager Chennai
HR_CHN = PanelMember(user_id="hr.chennai@axisbank.test", name="Bhuvana Kannan", role="hr_partner")
HM_CHN = PanelMember(user_id="vk.hm@axisbank.test", name="Venkat Krishnan", role="hiring_manager")
INT_CHN_1 = PanelMember(user_id="mr.int@axisbank.test", name="Mohan Raghavan", role="interviewer")

# Digital Product Gurugram (HQ)
HR_GGN = PanelMember(user_id="hr.ggn@axisbank.test", name="Tanya Bhatia", role="hr_partner")
HM_GGN = PanelMember(user_id="as.hm@axisbank.test", name="Aakash Singh", role="hiring_manager")
INT_GGN_1 = PanelMember(user_id="ng.int@axisbank.test", name="Nidhi Gupta", role="interviewer")
INT_GGN_2 = PanelMember(user_id="vc.int@axisbank.test", name="Vivek Chandra", role="interviewer")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def _build_jobs() -> list[Job]:
    # Resolve canonical Axis taxonomy entries up front so each Job below
    # is built from the same official role definition HR uses on Thrive.
    BDM_DESC, BDM_SKILLS, BDM_FUNC = _from_taxonomy(
        "10344062",
        fallback_skills=BDM_REQUIRED_SKILLS,
        fallback_description=(
            "Drive corporate salary account acquisition. Own end-to-end "
            "relationship from corporate sign-up through payroll onboarding "
            "and cross-sell of CASA, cards, loans and investments."
        ),
    )
    BRANCH_DESC, BRANCH_SKILLS, BRANCH_FUNC = _from_taxonomy(
        "10000549",
        fallback_skills=BRANCH_MANAGER_SKILLS,
        fallback_description=(
            "Lead a flagship branch. Own P&L, audit posture, customer "
            "experience and CASA growth targets."
        ),
    )
    WEALTH_DESC, WEALTH_SKILLS, WEALTH_FUNC = _from_taxonomy(
        "10344926",
        fallback_skills=WEALTH_RM_SKILLS,
        fallback_description=(
            "Manage a Burgundy Private book of HNI AUM. Drive advisory "
            "mandates, AIF/PMS placements and cross-sell."
        ),
        fallback_function="Wealth Management",
    )
    CREDIT_DESC, CREDIT_SKILLS, CREDIT_FUNC = _from_taxonomy(
        "10344453",
        fallback_skills=CREDIT_ANALYST_SKILLS,
        fallback_description=(
            "Underwrite mid-corporate credit proposals. Build financial "
            "models, draft CAM notes, present to credit committee."
        ),
        fallback_function="Wholesale Banking",
    )
    OPS_DESC, OPS_SKILLS, OPS_FUNC = _from_taxonomy(
        "10000553",
        fallback_skills=OPS_MANAGER_SKILLS,
        fallback_description=(
            "Cluster ops oversight. Drive zero operational losses, audit "
            "closures and process improvement."
        ),
    )
    DIGITAL_DESC, DIGITAL_SKILLS, DIGITAL_FUNC = _from_taxonomy(
        "120003442",
        fallback_skills=DIGITAL_PRODUCT_SKILLS,
        fallback_description=(
            "Own engagement & retention for Axis Mobile (35M+ MAU). Define "
            "the experiment roadmap, partner with design and engineering."
        ),
        fallback_function="Digital Banking",
    )

    return [
        # ---- BDM trio (matches the Thrive screenshot the demo references) ----
        Job(
            id="job-590321",
            job_id="590321",
            title="RB-LS:Business Development Manager - Corporate Salary Relationship",
            function=BDM_FUNC,
            band="DM",
            tags=["RB-BB", "RL & Products"],
            location="Bhopal",
            required_skills=BDM_SKILLS,
            nice_to_have_skills=["forex", "credit cards"],
            description=BDM_DESC,
            hr_partner_id=HR_BHOPAL.user_id,
            panel=[HR_BHOPAL, HM_BHOPAL, INT_BHOPAL_1, INT_BHOPAL_2],
            shortlist_threshold=75.0,
            positions=2,
        ),
        Job(
            id="job-592808",
            job_id="592808",
            title="RB-LS:Business Development Manager - Corporate Salary Relationship",
            function=BDM_FUNC,
            band="DM",
            tags=["RB-BB", "RL & Products"],
            location="Vadodara",
            required_skills=BDM_SKILLS,
            description=BDM_DESC,
            hr_partner_id="hr.vadodara@axisbank.test",
            panel=[
                PanelMember(user_id="hr.vadodara@axisbank.test", name="Amit Patel", role="hr_partner"),
                PanelMember(user_id="mk.hm@axisbank.test", name="Meera Krishnan", role="hiring_manager"),
                PanelMember(user_id="dt.int@axisbank.test", name="Deepak Thakur", role="interviewer"),
            ],
            shortlist_threshold=75.0,
        ),
        Job(
            id="job-595396",
            job_id="595396",
            title="RB-LS:Business Development Manager - Corporate Salary Relationship",
            function=BDM_FUNC,
            band="DM",
            tags=["RB-BB", "RL & Products"],
            location="Mysuru",
            required_skills=BDM_SKILLS,
            description=BDM_DESC,
            hr_partner_id="hr.mysuru@axisbank.test",
            panel=[
                PanelMember(user_id="hr.mysuru@axisbank.test", name="Lakshmi Iyer", role="hr_partner"),
                PanelMember(user_id="vr.hm@axisbank.test", name="Vikram Rao", role="hiring_manager"),
                PanelMember(user_id="sn.int@axisbank.test", name="Sneha Nair", role="interviewer"),
            ],
            shortlist_threshold=75.0,
        ),
        # ---- Branch Manager ----
        Job(
            id="job-601455",
            job_id="601455",
            title="RB-LS:Branch Manager - Flagship Branch",
            function=BRANCH_FUNC,
            band="SM",
            tags=["RB-BB", "Branch Banking"],
            location="Pune",
            required_skills=BRANCH_SKILLS,
            nice_to_have_skills=["wealth advisory", "regulatory liaison"],
            description=BRANCH_DESC,
            hr_partner_id=HR_PUNE.user_id,
            panel=[HR_PUNE, HM_PUNE, INT_PUNE_1],
            shortlist_threshold=78.0,
        ),
        # ---- Wealth RM ----
        Job(
            id="job-604772",
            job_id="604772",
            title="Burgundy Private:Senior Wealth Relationship Manager",
            function=WEALTH_FUNC,
            band="SM",
            tags=["Burgundy Private", "HNI"],
            location="Bengaluru",
            required_skills=WEALTH_SKILLS,
            nice_to_have_skills=["estate planning", "structured products"],
            description=WEALTH_DESC,
            hr_partner_id=HR_BLR.user_id,
            panel=[HR_BLR, HM_BLR, INT_BLR_1, INT_BLR_2],
            shortlist_threshold=80.0,
        ),
        # ---- Credit Analyst ----
        Job(
            id="job-608129",
            job_id="608129",
            title="WBG-Credit:Credit Analyst - Mid Corporate",
            function=CREDIT_FUNC,
            band="AM",
            tags=["WBG", "Credit"],
            location="Mumbai",
            required_skills=CREDIT_SKILLS,
            nice_to_have_skills=["working capital", "trade finance"],
            description=CREDIT_DESC,
            hr_partner_id=HR_MUM.user_id,
            panel=[HR_MUM, HM_MUM, INT_MUM_1],
            shortlist_threshold=78.0,
        ),
        # ---- Ops Manager ----
        Job(
            id="job-611038",
            job_id="611038",
            title="RB-Ops:Cluster Operations Manager",
            function=OPS_FUNC,
            band="DM",
            tags=["RB-Ops", "Compliance"],
            location="Chennai",
            required_skills=OPS_SKILLS,
            nice_to_have_skills=["RPA", "Six Sigma"],
            description=OPS_DESC,
            hr_partner_id=HR_CHN.user_id,
            panel=[HR_CHN, HM_CHN, INT_CHN_1],
            shortlist_threshold=75.0,
        ),
        # ---- Digital Product Manager ----
        Job(
            id="job-614902",
            job_id="614902",
            title="Digital Banking:Product Manager - Mobile App Engagement",
            function=DIGITAL_FUNC,
            band="SM",
            tags=["Digital", "Product"],
            location="Gurugram",
            required_skills=DIGITAL_SKILLS,
            nice_to_have_skills=["A/B testing", "growth experiments"],
            description=DIGITAL_DESC,
            hr_partner_id=HR_GGN.user_id,
            panel=[HR_GGN, HM_GGN, INT_GGN_1, INT_GGN_2],
            shortlist_threshold=80.0,
        ),
    ]


def seed_jobs() -> None:
    jobs = _build_jobs()
    # Live-demo override: swap every panel for real tenant users so the
    # orchestrator's free/busy + Teams-meeting calls hit real mailboxes.
    if _use_graph_panels():
        real_panel = _real_tenant_panel()
        for j in jobs:
            j.panel = list(real_panel)
            j.hr_partner_id = GRAPH_TENANT_HR.user_id

    for j in jobs:
        STORE.add_job(j)


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def _build_candidates() -> list[Candidate]:
    return [
        # ---- Strong BDM matches ----
        Candidate(
            id="cand-001",
            profile=Profile(
                employee_id="EMP10234",
                name="Rohan Verma",
                # Demo override: candidate "outreach" emails route to a real
                # Gmail so the stage demo can show the agent's R1 invite landing
                # on a phone in real time. Swap back to rohan.verma@axisbank.test
                # if you don't want live email delivery during a local run.
                email="siddharth.goyal90@gmail.com",
                current_role="Sr. Relationship Manager",
                current_location="Indore",
                current_band="AM",
                tenure_years=5.2,
                kras=[
                    "Grow branch CASA book by 15% YoY",
                    "Cross-sell 3+ products per relationship",
                    "Maintain NPS above 60",
                ],
                # Skills sourced from the Axis SKILL_MASTER taxonomy so the
                # match scorer can canonicalise both sides against the same
                # vocabulary HR uses internally on Thrive.
                skills=[
                    "Bank Sales",
                    "Business Development",
                    "Account Development",
                    "Commercial Banking",
                    "Banking Relationship Management",
                    "Business Partnering",
                ],
                education="MBA Finance, IIM Indore",
                last_rating="Exceeds Expectations",
            ),
        ),
        Candidate(
            id="cand-002",
            profile=Profile(
                employee_id="EMP10567",
                name="Ananya Iyer",
                email="ananya.iyer@axisbank.test",
                current_role="Branch Operations Manager",
                current_location="Surat",
                current_band="AM",
                tenure_years=6.8,
                kras=[
                    "Zero operational losses",
                    "Lead bulk corporate onboarding mandates",
                    "Team of 8 direct reports",
                ],
                skills=[
                    "corporate salary acquisition",
                    "KYC compliance",
                    "stakeholder management",
                    "portfolio sales",
                    "relationship management",
                    "branch operations",
                ],
                education="B.Com (Hons), Gujarat University",
                last_rating="Meets Expectations",
            ),
        ),
        Candidate(
            id="cand-003",
            profile=Profile(
                employee_id="EMP10891",
                name="Karthik Reddy",
                email="karthik.reddy@axisbank.test",
                current_role="Customer Service Manager",
                current_location="Hyderabad",
                tenure_years=3.4,
                kras=[
                    "Service desk SLA adherence",
                    "Drive digital adoption",
                ],
                skills=[
                    "relationship management",
                    "stakeholder management",
                    "CASA cross-sell",
                ],
                education="BBA, Osmania University",
            ),
        ),
        Candidate(
            id="cand-004",
            profile=Profile(
                employee_id="EMP11023",
                name="Priya Nair",
                email="priya.nair@axisbank.test",
                current_role="Wealth Relationship Manager",
                current_location="Kochi",
                current_band="AM",
                tenure_years=7.1,
                kras=[
                    "HNI portfolio of ₹120Cr",
                    "Advisory mandate renewals",
                ],
                # Full taxonomy-aligned BDM coverage so cand-004 is the
                # canonical "strong-fit" reference candidate the scoring
                # tests use as their high-water mark.
                skills=[
                    "Bank Sales",
                    "Business Development",
                    "Account Development",
                    "Commercial Banking",
                    "Employers Liability",
                    "Business Partnering",
                ],
                education="MBA, XIM Bhubaneswar",
                last_rating="Exceeds Expectations",
            ),
        ),
        Candidate(
            id="cand-005",
            profile=Profile(
                employee_id="EMP11544",
                name="Vikram Shah",
                email="vikram.shah@axisbank.test",
                current_role="Teller",
                current_location="Ahmedabad",
                tenure_years=1.5,
                kras=[
                    "Cash handling accuracy",
                    "Customer wait-time under 5 min",
                ],
                skills=["KYC compliance"],
            ),
        ),
        # ---- Branch Manager candidates ----
        Candidate(
            id="cand-006",
            profile=Profile(
                employee_id="EMP11890",
                name="Anil Deshmukh",
                email="anil.deshmukh@axisbank.test",
                current_role="Deputy Branch Manager",
                current_location="Pune",
                current_band="DM",
                tenure_years=9.4,
                kras=[
                    "Branch P&L of ₹42Cr",
                    "Lead 18 FTEs across sales & ops",
                    "100% audit closure within SLA",
                ],
                skills=[
                    "branch operations",
                    "team leadership",
                    "P&L ownership",
                    "audit & compliance",
                    "customer experience",
                    "CASA cross-sell",
                ],
                education="MBA, Symbiosis Pune",
                last_rating="Exceeds Expectations",
            ),
        ),
        Candidate(
            id="cand-007",
            profile=Profile(
                employee_id="EMP12044",
                name="Sunita Pillai",
                email="sunita.pillai@axisbank.test",
                current_role="Branch Manager - Tier 2",
                current_location="Nashik",
                current_band="DM",
                tenure_years=11.2,
                kras=[
                    "Branch P&L of ₹28Cr",
                    "Won 'Best Branch West' 2024",
                    "Mentor 3 BDMs",
                ],
                skills=[
                    "branch operations",
                    "team leadership",
                    "P&L ownership",
                    "audit & compliance",
                    "customer experience",
                    "CASA cross-sell",
                    "wealth advisory",
                ],
                education="B.Com, MMS Mumbai University",
                last_rating="Outstanding",
            ),
        ),
        Candidate(
            id="cand-008",
            profile=Profile(
                employee_id="EMP12330",
                name="Rakesh Bhandari",
                email="rakesh.bhandari@axisbank.test",
                current_role="Cluster Sales Lead",
                current_location="Pune",
                tenure_years=8.0,
                kras=["Cluster CASA growth 22% YoY"],
                skills=[
                    "team leadership",
                    "P&L ownership",
                    "CASA cross-sell",
                    "stakeholder management",
                ],
            ),
        ),
        # ---- Wealth RM candidates ----
        Candidate(
            id="cand-009",
            profile=Profile(
                employee_id="EMP12655",
                name="Meera Subramanian",
                email="meera.subramanian@axisbank.test",
                current_role="Wealth RM",
                current_location="Bengaluru",
                current_band="AM",
                tenure_years=6.5,
                kras=[
                    "AUM of ₹95Cr",
                    "Advisory mandate conversion 38%",
                ],
                skills=[
                    "HNI relationship management",
                    "portfolio advisory",
                    "mutual funds",
                    "AIF & PMS",
                    "KYC compliance",
                    "client acquisition",
                ],
                education="MBA, IIM Bangalore",
                last_rating="Exceeds Expectations",
            ),
        ),
        Candidate(
            id="cand-010",
            profile=Profile(
                employee_id="EMP12781",
                name="Aditya Menon",
                email="aditya.menon@axisbank.test",
                current_role="Investment Counsellor",
                current_location="Bengaluru",
                tenure_years=4.8,
                kras=["Drive structured product sales"],
                skills=[
                    "portfolio advisory",
                    "mutual funds",
                    "AIF & PMS",
                    "client acquisition",
                    "structured products",
                ],
                education="CFA Level III",
            ),
        ),
        Candidate(
            id="cand-011",
            profile=Profile(
                employee_id="EMP12902",
                name="Tara Krishnamurthy",
                email="tara.krishnamurthy@axisbank.test",
                current_role="Sr. Wealth RM",
                current_location="Chennai",
                current_band="SM",
                tenure_years=10.3,
                kras=[
                    "Burgundy Private book ₹180Cr",
                    "Estate planning lead for SI region",
                ],
                skills=[
                    "HNI relationship management",
                    "portfolio advisory",
                    "mutual funds",
                    "AIF & PMS",
                    "KYC compliance",
                    "client acquisition",
                    "estate planning",
                ],
                last_rating="Outstanding",
            ),
        ),
        # ---- Credit Analyst candidates ----
        Candidate(
            id="cand-012",
            profile=Profile(
                employee_id="EMP13110",
                name="Ishaan Bose",
                email="ishaan.bose@axisbank.test",
                current_role="Credit Analyst - SME",
                current_location="Mumbai",
                current_band="AM",
                tenure_years=3.9,
                kras=[
                    "Underwrite ₹120Cr SME book",
                    "Zero NPA on FY24 originations",
                ],
                skills=[
                    "credit underwriting",
                    "financial statement analysis",
                    "risk assessment",
                    "RBI compliance",
                    "MS Excel modelling",
                    "secured lending",
                ],
                education="CA (ICAI)",
                last_rating="Exceeds Expectations",
            ),
        ),
        Candidate(
            id="cand-013",
            profile=Profile(
                employee_id="EMP13245",
                name="Pooja Saxena",
                email="pooja.saxena@axisbank.test",
                current_role="Risk Officer",
                current_location="Mumbai",
                tenure_years=5.6,
                kras=["Portfolio quality monitoring"],
                skills=[
                    "risk assessment",
                    "RBI compliance",
                    "financial statement analysis",
                    "credit underwriting",
                ],
                education="MBA Finance, NMIMS",
            ),
        ),
        Candidate(
            id="cand-014",
            profile=Profile(
                employee_id="EMP13388",
                name="Harshad Mehta",
                email="harshad.mehta@axisbank.test",
                current_role="Trade Finance Officer",
                current_location="Mumbai",
                tenure_years=7.2,
                kras=["LC/BG issuance cycle time"],
                skills=[
                    "trade finance",
                    "working capital",
                    "RBI compliance",
                    "secured lending",
                ],
            ),
        ),
        # ---- Ops Manager candidates ----
        Candidate(
            id="cand-015",
            profile=Profile(
                employee_id="EMP13502",
                name="Lalitha Ramaswamy",
                email="lalitha.ramaswamy@axisbank.test",
                current_role="Branch Ops Lead",
                current_location="Chennai",
                current_band="AM",
                tenure_years=8.4,
                kras=[
                    "Audit score 96/100",
                    "Process automation rolled to 9 branches",
                ],
                skills=[
                    "branch operations",
                    "audit & compliance",
                    "team leadership",
                    "process improvement",
                    "KYC compliance",
                    "vendor management",
                    "Six Sigma",
                ],
                last_rating="Exceeds Expectations",
            ),
        ),
        Candidate(
            id="cand-016",
            profile=Profile(
                employee_id="EMP13644",
                name="Manish Agrawal",
                email="manish.agrawal@axisbank.test",
                current_role="Quality & Compliance Manager",
                current_location="Coimbatore",
                tenure_years=6.0,
                kras=["Drive RPA pilots"],
                skills=[
                    "audit & compliance",
                    "process improvement",
                    "RPA",
                    "vendor management",
                    "KYC compliance",
                ],
            ),
        ),
        # ---- Digital Product candidates ----
        Candidate(
            id="cand-017",
            profile=Profile(
                employee_id="EMP13780",
                name="Kavya Bhatt",
                email="kavya.bhatt@axisbank.test",
                current_role="Sr. Product Manager - Mobile",
                current_location="Gurugram",
                current_band="SM",
                tenure_years=7.8,
                kras=[
                    "Mobile DAU growth 21% YoY",
                    "Lead 4-PM pod",
                ],
                skills=[
                    "product management",
                    "user research",
                    "analytics SQL",
                    "stakeholder management",
                    "agile delivery",
                    "mobile banking",
                    "A/B testing",
                ],
                education="MBA, ISB Hyderabad",
                last_rating="Outstanding",
            ),
        ),
        Candidate(
            id="cand-018",
            profile=Profile(
                employee_id="EMP13899",
                name="Yash Malhotra",
                email="yash.malhotra@axisbank.test",
                current_role="Product Analyst",
                current_location="Bengaluru",
                tenure_years=3.1,
                kras=["Define KPI dashboards"],
                skills=[
                    "analytics SQL",
                    "user research",
                    "agile delivery",
                    "product management",
                ],
                education="B.Tech, BITS Pilani",
            ),
        ),
        Candidate(
            id="cand-019",
            profile=Profile(
                employee_id="EMP14002",
                name="Sneha Kapoor",
                email="sneha.kapoor@axisbank.test",
                current_role="UX Researcher",
                current_location="Gurugram",
                tenure_years=4.4,
                kras=["Run quarterly usability studies"],
                skills=[
                    "user research",
                    "stakeholder management",
                    "mobile banking",
                ],
            ),
        ),
        # ---- Generalists / cross-fit candidates ----
        Candidate(
            id="cand-020",
            profile=Profile(
                employee_id="EMP14118",
                name="Rajat Khanna",
                email="rajat.khanna@axisbank.test",
                current_role="Area Sales Manager",
                current_location="Lucknow",
                current_band="DM",
                tenure_years=9.0,
                kras=[
                    "North zone CASA growth",
                    "Mentor 12 BDMs",
                ],
                skills=[
                    "corporate salary acquisition",
                    "relationship management",
                    "portfolio sales",
                    "stakeholder management",
                    "KYC compliance",
                    "CASA cross-sell",
                    "team leadership",
                ],
                last_rating="Exceeds Expectations",
            ),
        ),
        Candidate(
            id="cand-021",
            profile=Profile(
                employee_id="EMP14240",
                name="Deepika Menon",
                email="deepika.menon@axisbank.test",
                current_role="Relationship Manager",
                current_location="Vadodara",
                tenure_years=4.6,
                kras=["Corporate salary acquisition target 110%"],
                skills=[
                    "corporate salary acquisition",
                    "relationship management",
                    "portfolio sales",
                    "KYC compliance",
                    "CASA cross-sell",
                ],
            ),
        ),
        Candidate(
            id="cand-022",
            profile=Profile(
                employee_id="EMP14377",
                name="Nikhil Joshi",
                email="nikhil.joshi@axisbank.test",
                current_role="Relationship Manager",
                current_location="Mysuru",
                tenure_years=3.8,
                kras=["Tech-park onboarding"],
                skills=[
                    "corporate salary acquisition",
                    "relationship management",
                    "stakeholder management",
                    "CASA cross-sell",
                ],
            ),
        ),
    ]


def seed_candidates() -> None:
    cands = _build_candidates()

    # Live-demo override: when running against real Microsoft Graph, re-point
    # EMP10234 at the real tenant mailbox Rohan Desai so that outreach email,
    # free/busy calls, and Teams invites all resolve against a real inbox
    # instead of the synthetic siddharth.goyal90@gmail.com placeholder used
    # for local runs. The synthetic identity remains the default for mock
    # mode + tests.
    if _use_graph_panels():
        for c in cands:
            if c.profile.employee_id == "EMP10234":
                c.profile.name = GRAPH_TENANT_CANDIDATE_NAME
                c.profile.email = GRAPH_TENANT_CANDIDATE_UPN
                break

    for c in cands:
        STORE.add_candidate(c)


def _build_panels() -> list[Panel]:
    """Seed a curated panel catalogue (DESIGN-001).

    Role scopes are matched against JD function and band in
    ``panels_for_job``. Wildcard ``"*"`` matches any JD. In graph mode,
    panels contain the real Xebia192 tenant mailboxes so multi-user
    free/busy intersections drive real slot proposals.
    """
    if _use_graph_panels():
        # Each panel has Suresh Kumar (real Graph mailbox — live free/busy)
        # plus distinct synthetic stubs so HR sees visually different
        # rosters per panel. Stub members are treated as "always free" by
        # the GraphCalendarProvider (see _STUB_SUFFIX handling).
        #
        # Scope notes (2026-04-07): the Axis taxonomy classifies "Branch
        # Manager" jobs under function="Branch Banking" (a child of Retail
        # Banking), so panels that should be eligible for those JDs MUST
        # list "Branch Banking" / "Branch Banking/SM" in their role_scopes
        # — otherwise panels_for_job() returns an empty set and HR sees
        # "No panels match this JD's function/band" on the R2 approval
        # card. We add a dedicated Pune Branch Banking panel and also
        # broaden the existing senior retail panel to cover Branch
        # Banking, so HR has at least one in-region option AND one
        # zonal fallback.
        return [
            Panel(
                id="panel-bdm-central",
                name="Central Zone BDM Panel",
                members=[GRAPH_TENANT_HM],
                role_scopes=["Retail Banking/DM", "Retail Banking"],
                location="Bhopal",
                default_size=1,
                active=True,
            ),
            Panel(
                id="panel-retail-senior",
                name="Retail Banking Senior Panel",
                members=[GRAPH_TENANT_HM],
                role_scopes=[
                    "Retail Banking/SM",
                    "Retail Banking",
                    "Branch Banking",
                    "Branch Banking/SM",
                ],
                location="Mumbai",
                default_size=1,
                active=True,
            ),
            Panel(
                id="panel-branch-pune",
                name="Pune Branch Banking Panel",
                members=[GRAPH_TENANT_HM],
                role_scopes=[
                    "Branch Banking",
                    "Branch Banking/SM",
                    "Retail Banking",
                    "Retail Banking/SM",
                ],
                location="Pune",
                default_size=1,
                active=True,
            ),
            Panel(
                id="panel-wholesale-credit",
                name="Wholesale Credit Panel",
                members=[GRAPH_STUB_KARTHIK],
                role_scopes=["Wholesale Banking", "Wholesale Banking/AM"],
                location="Mumbai",
                default_size=1,
                active=True,
            ),
        ]
    return [
        Panel(
            id="panel-bdm-central",
            name="Central Zone BDM Panel",
            members=[HM_BHOPAL],
            role_scopes=["Retail Banking/DM", "Retail Banking"],
            location="Bhopal",
            default_size=1,
            active=True,
        ),
        Panel(
            id="panel-branch-west",
            name="Western Region Branch Manager Panel",
            members=[HM_PUNE],
            role_scopes=[
                "Retail Banking/SM",
                "Retail Banking",
                "Branch Banking",
                "Branch Banking/SM",
            ],
            location="Pune",
            default_size=1,
            active=True,
        ),
        Panel(
            id="panel-wealth-south",
            name="South Wealth HNI Panel",
            members=[HM_BLR],
            role_scopes=["Wealth Management", "Wealth Management/SM"],
            location="Bengaluru",
            default_size=1,
            active=True,
        ),
        Panel(
            id="panel-credit-mum",
            name="Mumbai Mid-Corporate Credit Panel",
            members=[HM_MUM],
            role_scopes=["Wholesale Banking", "Wholesale Banking/AM"],
            location="Mumbai",
            default_size=1,
            active=True,
        ),
        Panel(
            id="panel-ops-south",
            name="South Ops Panel",
            members=[HM_CHN],
            role_scopes=["Retail Banking/DM", "Retail Banking"],
            location="Chennai",
            default_size=1,
            active=True,
        ),
        Panel(
            id="panel-digital-hq",
            name="Digital Banking HQ Panel",
            members=[HM_GGN],
            role_scopes=["Digital Banking", "Digital Banking/SM"],
            location="Gurugram",
            default_size=1,
            active=True,
        ),
    ]


def seed_panels() -> None:
    for p in _build_panels():
        STORE.add_panel(p)


def panels_for_job(job: Job) -> list[Panel]:
    """Filter the panel catalogue down to panels qualified for this JD.

    Matching rules (any-hit wins):
      * ``"*"`` matches any JD
      * ``"<function>"`` matches any JD in that function
      * ``"<function>/<band>"`` matches only JDs in that function + band
      * ``"<band>"`` matches any JD at that band regardless of function

    Only ``active`` panels are returned.
    """
    func = (job.function or "").strip()
    band = (job.band or "").strip()
    qualified_key = f"{func}/{band}" if func and band else None

    out: list[Panel] = []
    for p in STORE.list_panels():
        if not p.active:
            continue
        for scope in p.role_scopes:
            s = scope.strip()
            if s == "*":
                out.append(p)
                break
            if qualified_key and s == qualified_key:
                out.append(p)
                break
            if s == func:
                out.append(p)
                break
            if s == band:
                out.append(p)
                break
    return out


def seed_all() -> None:
    STORE.reset()
    seed_jobs()
    seed_candidates()
    seed_panels()
