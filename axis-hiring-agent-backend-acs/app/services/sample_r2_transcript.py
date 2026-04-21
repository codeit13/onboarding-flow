"""Canned R2 transcripts auto-populated on every R2 interview record.

In production each panellist's 1-on-1 transcript would come from the
Microsoft Graph Teams transcript API for THAT panellist's individual
meeting with the candidate. For the demo we pre-seed a distinct realistic
sample per panellist (keyed by index in the panel) so HR can run a per
panellist AI review and see Claude corroborate or challenge each vote
independently — exactly as if every panellist had run their own meeting.
"""

from typing import Dict, List

SAMPLE_R2_TRANSCRIPT = """Panel: Thanks for joining. Walk us through your last 12 months in role — what were the two or three things you owned end-to-end?
Candidate: Sure. The biggest one was the Burgundy upgrade drive — we had ~280 mass-affluent customers sitting just below the Burgundy AUM threshold. I built a daily call-list off the CRM, paired each RM with a portfolio analyst, and we ran a 90-day push. We converted 71 of them, which added about ₹84 crore in book value. The second was a CASA acquisition tie-up with three local CA firms — that gave us 140 new current accounts in Q3. And the third was cleaning up our KYC re-verification backlog; we were running at 11% non-compliant and we got it under 2% in two quarters.

Panel: On the Burgundy push — what did you do when an RM pushed back saying the customer wasn't ready?
Candidate: Two things. First, I asked the RM to walk me through the last three conversations on the CRM notes. Usually it was a pricing objection, not a readiness issue. Second, if the customer genuinely wasn't ready, I had the RM mark them in a "nurture" bucket with a 60-day follow-up — I did not want them to feel hounded. The point of the drive was to find the customers who were already there mentally, not to force-fit anyone.

Panel: How do you think about cross-sell without it becoming pushy?
Candidate: I think the line is whether the next product solves a real problem the customer has already told you about. If a customer mentions their daughter's college admission, that's a goal — an SIP or an education loan is a fit. If they haven't told you anything and you're just hitting a target, the customer can smell it. I track cross-sell quality by the 6-month retention of the second product, not the day-one sale.

Panel: Tell us about a time you disagreed with your zonal head.
Candidate: Last year my zonal head wanted me to shut down our Saturday open-house at the branch — footfall was lower than weekday and he wanted the staff cost back. I pulled the data and showed that 60% of our Burgundy upgrades in Q2 had their first meaningful conversation on a Saturday. I asked for one more quarter to prove it, with a clear KPI — if Saturday conversions dropped below 40% I'd shut it myself. He agreed. The number held at 58%, and we kept it.

Panel: You'd be moving markets for this role. What's your read on the new geography versus your current one?
Candidate: It's structurally different — more government employees, less SME density, and the affluent base is older. I'd expect the Burgundy playbook to work but slower, and I'd expect CASA acquisition to be harder because the SME pipeline is thinner. I'd want to spend the first 30 days riding along with the existing RMs before I change anything. I'd be cautious about importing my current plan wholesale.

Panel: A regulatory question — if you spotted a suspected mis-selling complaint on a ULIP sold by one of your RMs, what's the first thing you do?
Candidate: First, I pull the call recording and the needs-analysis form and read both before I talk to anyone. Second, I loop in compliance — same day, in writing — even before I talk to the RM, because the RM conversation has to be witnessed. Third, I call the customer myself, acknowledge the concern, and explain the grievance redressal path. I don't try to "save" the sale at that point; the priority is protecting the customer and the bank.

Panel: One last one — what's a weakness you're actively working on?
Candidate: I am not great at delegating analytics work. I tend to pull the data myself because I trust my own SQL more than the dashboards. It's slower and it doesn't scale. I've started forcing myself to write the question down and hand it to my MIS analyst, even when I know I could pull it in five minutes. I've kept it up for about three months now.

Panel: Thanks, that's all from us. Anything you want to ask?
Candidate: Two questions — what does the panel see as the single biggest risk to the book in the next 12 months, and how is the bank thinking about the role of branch managers as more of the routine business moves to the app?
"""


# ---------------------------------------------------------------------------
# Per-panellist variants
# ---------------------------------------------------------------------------
#
# Each panellist runs their own 1-on-1 with the candidate. The conversations
# overlap on theme but not on content — each interviewer probes a different
# angle. The orchestrator pre-seeds these so HR can run a separate Claude
# review per panellist on the R2 review screen.

_HIRING_MANAGER_TRANSCRIPT = """Hiring Manager: Walk me through the single most important number on your branch P&L last year and what you did about it.
Candidate: It was the cost-to-income ratio — we were sitting at 56%. I cut it to 49% over three quarters. Two moves: I renegotiated the AMC on the cash-handling vendor (saved ~₹14L) and I shifted three FTEs from teller work into RM-assist roles after we pushed transactions to the app.

Hiring Manager: How did the team take the FTE shift?
Candidate: Two of them were nervous because they had been tellers for 8+ years. I sat with each of them for an hour, walked through what RM-assist would actually look like day-to-day, and committed to a 60-day buddy programme. One of them is now my best lead-qualifier.

Hiring Manager: This role has a P0 on Burgundy AUM growth in a slower geography. What's your 30-day plan?
Candidate: 30 days, I don't change anything. I sit with the top 3 RMs, ride along on 10 customer meetings, read the last 6 months of CRM notes, and pull the pipeline by stage. I want to know where the leakage is before I touch the playbook. Day 31 I put out a hypothesis with the team, not a directive.

Hiring Manager: If I told you your AUM target was 20% higher than what's on the JD, what would you push back on?
Candidate: I'd ask for two things — a clear view of which customer segments the extra 20% is supposed to come from, and either a headcount add or a cost-per-lead budget for an outbound campaign. I would not just absorb it silently, because then the team carries the stress and you lose trust.

Hiring Manager: Why are you actually leaving your current role?
Candidate: I am not running from anything. I have hit the ceiling in my current zone — the book is mature, the team is steady, and there is not much left for me to learn there. I want a market where I have to rebuild the playbook, not run someone else's.
"""


_TECHNICAL_INTERVIEWER_TRANSCRIPT = """Interviewer: Let's go technical. Walk me through how you read a branch P&L — what are the first three lines you look at?
Candidate: NII first, because it tells me whether the asset and liability mix is actually working. Then fee income split — I want to know if it is concentrated in two products or spread. Third, provisions and write-offs against the prior four quarters; if provisions are spiking, something in the underwriting is off.

Interviewer: A customer walks in with a ₹2 crore inward remittance flagged by AML. What is your sequence?
Candidate: I do not release the funds. I pull the source-of-funds documents, the customer's risk rating, and the past six months of account activity. I escalate to the branch compliance officer the same day with a written note. If the customer is on the floor, I tell them politely that we are running a standard verification and we will revert within 24 to 48 hours. I do not let an RM "handle it" off-record.

Interviewer: What's your read on RBI's recent priority sector lending tweaks for MSME?
Candidate: The shift to weighted-asset categorisation is going to push more banks toward smaller-ticket MSME loans because the weighting is friendlier. For a branch like mine, that means I need my RM team trained on the under-₹50L MSME segment specifically — that's where the volume is going to come from, and we are not great at it yet.

Interviewer: How comfortable are you with Finacle and our CRM stack?
Candidate: Finacle every day for 7 years — TD opening, lien marking, NEFT/RTGS overrides, the whole thing. CRM I'm strong on the lead-management module and the activity tracker. Where I'm weaker is the analytics dashboard — I tend to pull reports through the MIS team rather than running them myself. I'm working on it.

Interviewer: One regulatory miss in your career — what was it and what did you change after?
Candidate: An RM on my team booked a SIP for a senior citizen without filing the suitability assessment. I caught it on the monthly audit. I self-reported to compliance, refunded the customer, and rebuilt our pre-sale checklist so suitability is a hard gate in the CRM, not a paper form. Zero repeats since.
"""


_STRATEGY_INTERVIEWER_TRANSCRIPT = """Interviewer: If you had to pick one customer segment to double down on for this branch in the next 12 months, which one and why?
Candidate: NRI — specifically Gulf-returning families in the 35 to 50 bracket. They come back with a corpus, they need an account opened fast, they need investment advice, and they almost always have a property purchase planned in the first 18 months. If I get the first conversation right, I get the home loan, the SIP, the insurance, and the children's education plan. It's the highest lifetime-value cohort in this geography.

Interviewer: Where would you NOT play?
Candidate: I would not chase ultra-HNI in this market — the wealth-management infrastructure is not strong enough yet and we'd lose the customer to a private bank within a year. I'd rather refer them upstream to the central wealth team than half-deliver in branch.

Interviewer: How do you think about branch versus app cannibalisation?
Candidate: The app is a feature, not a competitor. The transactions that move to the app — balance check, fund transfer, mini statement — were never the high-value moments anyway. What stays in the branch is the conversation. My job is to make sure the customer who walks in actually gets a conversation, not a queue ticket.

Interviewer: A peer branch manager poaches one of your top RMs. What do you do?
Candidate: First, I ask the RM honestly why they were open to it — usually it is not money, it is a manager problem or a growth problem on my side. If it's something I can fix, I fix it and I tell them what changed. If they still want to go, I let them go cleanly and I help them transition — banking is small, you'll work with them again. I do not get into a counter-offer war.

Interviewer: Where do you want to be in five years?
Candidate: Cluster head, ideally in a market I have built from a single branch. I want the operating experience of running 8 to 12 branches before I take any central role. I'm not in a rush to leave the field.
"""


# Module-level list — orchestrator picks one per panellist by index, cycling
# if the panel has more than three members.
SAMPLE_R2_TRANSCRIPT_VARIANTS: List[str] = [
    _HIRING_MANAGER_TRANSCRIPT,
    _TECHNICAL_INTERVIEWER_TRANSCRIPT,
    _STRATEGY_INTERVIEWER_TRANSCRIPT,
]


def transcripts_for_panel(panellist_ids: List[str]) -> Dict[str, str]:
    """Return a {panellist_id: transcript} dict, one variant per panellist.

    The variants cycle deterministically by index so re-renders are stable
    and tests can assert exact text. The first panellist always gets the
    hiring-manager transcript, the second gets the technical one, etc.
    """
    if not SAMPLE_R2_TRANSCRIPT_VARIANTS:
        return {pid: SAMPLE_R2_TRANSCRIPT for pid in panellist_ids}
    out: Dict[str, str] = {}
    for idx, pid in enumerate(panellist_ids):
        out[pid] = SAMPLE_R2_TRANSCRIPT_VARIANTS[
            idx % len(SAMPLE_R2_TRANSCRIPT_VARIANTS)
        ]
    return out

