// Canned R2 transcript used for demo / dry-runs of the AI analysis flow.
//
// Realistic enough that the AI agent has signal to score against the JD
// rubric (skills, situational judgement, red flags). Loosely modelled on a
// Branch Manager / BDM conversation in the RB-LS function — generic enough
// to work for any of the seeded JDs.
export const SAMPLE_R2_TRANSCRIPT = `Panel: Thanks for joining, Rohan. Walk us through your last 12 months at the Indore branch — what were the two or three things you owned end-to-end?
Candidate: Sure. The biggest one was the Burgundy upgrade drive — we had ~280 mass-affluent customers sitting just below the Burgundy AUM threshold. I built a daily call-list off the CRM, paired each RM with a portfolio analyst, and we ran a 90-day push. We converted 71 of them, which added about ₹84 crore in book value. The second was a CASA acquisition tie-up with three local CA firms — that gave us 140 new current accounts in Q3. And the third was cleaning up our KYC re-verification backlog; we were running at 11% non-compliant and we got it under 2% in two quarters.

Panel: On the Burgundy push — what did you do when an RM pushed back saying the customer wasn't ready?
Candidate: Two things. First, I asked the RM to walk me through the last three conversations on the CRM notes. Usually it was a pricing objection, not a readiness issue. Second, if the customer genuinely wasn't ready, I had the RM mark them in a "nurture" bucket with a 60-day follow-up — I did not want them to feel hounded. The point of the drive was to find the customers who were already there mentally, not to force-fit anyone.

Panel: How do you think about cross-sell without it becoming pushy?
Candidate: I think the line is whether the next product solves a real problem the customer has already told you about. If a customer mentions their daughter's college admission, that's a goal — an SIP or an education loan is a fit. If they haven't told you anything and you're just hitting a target, the customer can smell it. I track cross-sell quality by the 6-month retention of the second product, not the day-one sale.

Panel: Tell us about a time you disagreed with your zonal head.
Candidate: Last year my zonal head wanted me to shut down our Saturday open-house at the branch — footfall was lower than weekday and he wanted the staff cost back. I pulled the data and showed that 60% of our Burgundy upgrades in Q2 had their first meaningful conversation on a Saturday. I asked for one more quarter to prove it, with a clear KPI — if Saturday conversions dropped below 40% I'd shut it myself. He agreed. The number held at 58%, and we kept it.

Panel: You'd be moving to Bhopal for this role. What's your read on that market versus Indore?
Candidate: Bhopal is structurally different — more government employees, less SME density, and the affluent base is older. I'd expect the Burgundy playbook to work but slower, and I'd expect CASA acquisition to be harder because the SME pipeline is thinner. I'd want to spend the first 30 days riding along with the existing RMs before I change anything. I'd be cautious about importing the Indore plan wholesale.

Panel: A regulatory question — if you spotted a suspected mis-selling complaint on a ULIP sold by one of your RMs, what's the first thing you do?
Candidate: First, I pull the call recording and the needs-analysis form and read both before I talk to anyone. Second, I loop in compliance — same day, in writing — even before I talk to the RM, because the RM conversation has to be witnessed. Third, I call the customer myself, acknowledge the concern, and explain the grievance redressal path. I don't try to "save" the sale at that point; the priority is protecting the customer and the bank.

Panel: One last one — what's a weakness you're actively working on?
Candidate: I am not great at delegating analytics work. I tend to pull the data myself because I trust my own SQL more than the dashboards. It's slower and it doesn't scale. I've started forcing myself to write the question down and hand it to my MIS analyst, even when I know I could pull it in five minutes. I've kept it up for about three months now.

Panel: Thanks Rohan, that's all from us. Anything you want to ask?
Candidate: Two questions — what does the panel see as the single biggest risk to the Bhopal book in the next 12 months, and how is the bank thinking about the role of branch managers as more of the routine business moves to the app?
`;
