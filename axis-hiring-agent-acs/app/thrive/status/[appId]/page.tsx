"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  api,
  acceptOffer,
  declineOffer,
  getEngagementByApplication,
  getOnboardingChat,
  sendOnboardingChat,
  type AgentStatus,
  type Application,
  type ConversationMessage,
  type EngagementJourney,
  type EngagementTouchpoint,
  type FunnelStage,
  type InterviewRecord,
  type InterviewReport,
  type Job,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { STAGE_LABEL, STAGE_ORDER } from "@/lib/stages";

/**
 * Employee-facing live status page (the "after" half of the guided Apply flow).
 *
 * Three things must always be visible at a glance:
 *  1. WHAT IS HAPPENING NOW   — narrative bound to (stage × agent_status)
 *  2. WHAT HAPPENS NEXT       — explicit next step the agent will take
 *  3. WHAT DO I DO            — when agent_status is waiting_candidate, the
 *                                user gets a slot picker right inline
 */

export default function EmployeeStatusPage() {
  return (
    <RoleGate allow={["employee"]}>
      <EmployeeStatusContent />
    </RoleGate>
  );
}

interface Narrative {
  now: string;
  next: string;
  tone: "info" | "action" | "success" | "danger";
}

function narrativeFor(app: Application): Narrative {
  const stage: FunnelStage = app.stage;
  const status: AgentStatus = app.agent_status;

  if (stage === "rejected") {
    return {
      now: "We're sorry — your application for this role isn't moving forward.",
      next: "You'll receive an email from us shortly. We'd love to see you apply for other roles at Axis that match your strengths.",
      tone: "danger",
    };
  }
  if (stage === "offer_negotiation") {
    return {
      now: "🎉 You've cleared the panel interview! Axis has approved your offer in principle.",
      next: "Our compensation team is finalising the details and will reach out shortly with your formal offer letter.",
      tone: "success",
    };
  }
  if (stage === "offer") {
    if (status === "waiting_candidate_acceptance") {
      return {
        now: "Your formal offer is ready! Please review and accept to start your onboarding journey.",
        next: "Once you accept, we'll kick off a personalised engagement journey to keep you connected with your new team until Day 1.",
        tone: "action",
      };
    }
    return {
      now: "Your formal offer has been sent. Welcome to Axis!",
      next: "Check your inbox for the offer letter — it covers your CTC, joining bonus and onboarding steps. We can't wait to have you on board.",
      tone: "success",
    };
  }
  if (stage === "offer_accepted") {
    return {
      now: "Congratulations! You've accepted the offer. We're thrilled to have you joining Axis Bank!",
      next: "Your onboarding journey has started. You'll receive WhatsApp messages with helpful information, document checklists, and team introductions leading up to your joining date.",
      tone: "success",
    };
  }
  if (stage === "pre_joining") {
    return {
      now: "Your joining date is coming up! We're getting everything ready for your Day 1.",
      next: "Please complete any pending document submissions and IT setup forms. Your buddy and team lead are looking forward to meeting you.",
      tone: "info",
    };
  }
  if (stage === "joined") {
    return {
      now: "Welcome aboard! You're officially part of the Axis Bank family.",
      next: "Your onboarding team will guide you through your first week. Check with your buddy if you have any questions.",
      tone: "success",
    };
  }
  if (stage === "offer_declined") {
    return {
      now: "We understand your decision. We wish you all the best in your future endeavours.",
      next: "If you change your mind or would like to explore other roles at Axis Bank in the future, our doors are always open.",
      tone: "danger",
    };
  }
  if (stage === "applied") {
    if (status === "waiting_hr") {
      return {
        now: "Your application is with the Axis hiring team for review.",
        next: "We'll be in touch soon with next steps. This page will refresh automatically as soon as there's an update.",
        tone: "info",
      };
    }
    return {
      now: "We're reviewing your profile against this role right now.",
      next: "Once we're done, the Axis hiring team will either invite you to Round 1 or get in touch directly.",
      tone: "info",
    };
  }
  if (stage === "screened" && status === "running") {
    return {
      now: "We're checking your availability against the hiring team's calendar to suggest interview times that work for you.",
      next: "You'll see 3 suggested time slots here in just a moment.",
      tone: "info",
    };
  }
  if (stage === "screened" && status === "waiting_candidate") {
    return {
      now: "We've found 3 interview times that work for you — pick the one you prefer.",
      next: "Once you confirm, we'll send you the Microsoft Teams invite by email and add it to your calendar.",
      tone: "action",
    };
  }
  if (stage === "screened" && status === "waiting_hr") {
    return {
      now: "We couldn't find a common interview slot in the next few days, so the Axis hiring team is stepping in to help.",
      next: "Your hiring contact will either open up a fresh time on the panel calendar or reach out directly. This page will refresh automatically as soon as new slots are ready.",
      tone: "danger",
    };
  }
  if (stage === "r1_scheduled") {
    if (!app.r1_started) {
      return {
        now: "Your Round 1 interview is booked. Whenever you're ready, click 'Start interview' below to begin.",
        next: "It's a short conversational interview — we'll ask a few role-related questions and you can answer at your own pace. You'll see your result here a few seconds after you finish.",
        tone: "action",
      };
    }
    return {
      now: "Thanks for completing your Round 1 interview! We're putting your result together now.",
      next: "This usually takes a few seconds. The page will refresh automatically with your result and what happens next.",
      tone: "info",
    };
  }
  if (stage === "r1_done") {
    if (status === "waiting_hr") {
      return {
        now: "You've cleared Round 1 — congratulations! The Axis hiring team is lining up your Round 2 panel interview now.",
        next: "We'll suggest 3 Round 2 time slots for you to choose from as soon as the panel is confirmed.",
        tone: "info",
      };
    }
    if (status === "waiting_candidate" && app.proposed_r2_slots.length > 0) {
      return {
        now: "Three Round 2 panel interview times are ready for you below — pick the one that works best.",
        next: "Once you confirm, we'll send you the Teams invite and brief the panel ahead of the conversation.",
        tone: "action",
      };
    }
    return {
      now: "You've cleared Round 1 — congratulations! We're lining up your Round 2 panel interview now.",
      next: "We'll suggest 3 Round 2 time slots for you to choose from as soon as the panel is confirmed.",
      tone: "info",
    };
  }
  if (stage === "r2_scheduled") {
    return {
      now: "Your Round 2 panel interview is scheduled.",
      next: "After Round 2, the panel will share their feedback and we'll get back to you with the outcome.",
      tone: "info",
    };
  }
  return {
    now: "We're working on your application.",
    next: "This page updates live as your application moves forward.",
    tone: "info",
  };
}

function EmployeeStatusContent() {
  const params = useParams<{ appId: string }>();
  const router = useRouter();
  const [confirming, setConfirming] = useState<number | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [startingR1, setStartingR1] = useState(false);
  const [startR1Error, setStartR1Error] = useState<string | null>(null);
  // UX: between "I confirmed a slot" and "the orchestrator finished
  // booking the Teams meeting" the page used to silently sit on the
  // old waiting_candidate state for several seconds, which read as
  // "nothing happened". This sticky overlay closes that gap with a
  // visible processing banner that we keep up until the funnel
  // actually advances. The same banner is reused for any other
  // long-running orchestrator transition (start R1, reschedule).
  const [transitionLabel, setTransitionLabel] = useState<string | null>(null);

  // "Selection ≠ commitment" — clicking a slot tile only stages a
  // pending choice. A confirm dialog then asks the candidate to
  // explicitly book it. Same for the Start R1 CTA.
  const [pendingR1Slot, setPendingR1Slot] = useState<number | null>(null);
  const [pendingR2Slot, setPendingR2Slot] = useState<number | null>(null);
  const [pendingStartR1, setPendingStartR1] = useState(false);
  // Reschedule flow — pendingReschedule is the round currently in the
  // confirm dialog (R1/R2 or null when no dialog is open).
  const [pendingReschedule, setPendingReschedule] = useState<"R1" | "R2" | null>(null);
  const [rescheduleError, setRescheduleError] = useState<string | null>(null);

  // Custom R1 slot flow ("Start now" + user-picked date/time). Only used
  // for R1 because Round 1 is an AI-driven interview that does not need a
  // real panel intersection — the candidate is free to run it immediately
  // or at any custom time. `pendingCustomR1Start` is the ISO datetime the
  // candidate has staged in the confirm dialog (null = dialog closed).
  const [pendingCustomR1Start, setPendingCustomR1Start] = useState<string | null>(null);
  const [customR1Mode, setCustomR1Mode] = useState<"now" | "later">("now");

  // Offer accept / decline state
  const [offerPhone, setOfferPhone] = useState("");
  const [offerConsent, setOfferConsent] = useState(true);
  const [offerJoiningDate, setOfferJoiningDate] = useState("");
  const [offerSubmitting, setOfferSubmitting] = useState(false);
  const [offerError, setOfferError] = useState<string | null>(null);
  const [declineReason, setDeclineReason] = useState("");
  const [showDeclineForm, setShowDeclineForm] = useState(false);
  const [engagementJourney, setEngagementJourney] = useState<EngagementJourney | null>(null);

  // Candidate onboarding chatbot (post-offer only)
  const [chatMessages, setChatMessages] = useState<ConversationMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [journeyExpanded, setJourneyExpanded] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  const loadApp = useCallback(
    () => api.getApplication(params.appId),
    [params.appId],
  );
  const { data: rawApp, error, refresh } = useAutoRefresh<Application>(loadApp, 3000);
  // If the backend no longer knows this id (e.g. it was restarted and the
  // in-memory store was wiped), drop the stale cached app so we show the
  // "application no longer exists" empty state instead of rendering a page
  // full of dead action buttons.
  const appMissing = !!error && /404/.test(error);
  const app = appMissing ? null : rawApp;

  // Fetch the JD once we know which job_id this application is bound to,
  // so the header can show the role title, location, band etc. — instead
  // of just the opaque "JD job-590321" code.
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    if (!app?.job_id) return;
    let cancelled = false;
    api
      .getJob(app.job_id)
      .then((j) => {
        if (!cancelled) setJob(j);
      })
      .catch(() => {
        /* non-fatal: header just falls back to job_id */
      });
    return () => {
      cancelled = true;
    };
  }, [app?.job_id]);

  // Load engagement journey for post-offer stages
  useEffect(() => {
    if (!app) return;
    if (app.stage === "offer_accepted" || app.stage === "pre_joining") {
      getEngagementByApplication(app.id)
        .then(setEngagementJourney)
        .catch(() => {});
      // Load onboarding chatbot history
      getOnboardingChat(app.id)
        .then((d) => setChatMessages(d.messages || []))
        .catch(() => {});
    }
  }, [app?.id, app?.stage]);

  const onSendChat = async () => {
    if (!app || !chatInput.trim() || chatSending) return;
    const q = chatInput.trim();
    setChatSending(true);
    setChatError(null);
    // optimistic append of user turn
    const optimistic: ConversationMessage = {
      id: `local-${Date.now()}`,
      journey_id: engagementJourney?.id || "",
      direction: "inbound",
      sender: app.candidate_name || "You",
      body: q,
      channel: "portal",
      touchpoint_id: null,
      reply_to_id: null,
      whatsapp_message_id: null,
      timestamp: new Date().toISOString(),
      status: "sending",
    };
    setChatMessages((prev) => [...prev, optimistic]);
    setChatInput("");
    try {
      const res = await sendOnboardingChat(app.id, q);
      // replace optimistic with the real persisted pair
      setChatMessages((prev) => {
        const withoutLocal = prev.filter((m) => m.id !== optimistic.id);
        return [...withoutLocal, res.inbound, res.outbound];
      });
    } catch (e: any) {
      setChatError(e?.message || "Could not send. Please try again.");
      // rollback optimistic
      setChatMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
    } finally {
      setChatSending(false);
    }
  };

  const stageIdx = app ? STAGE_ORDER.indexOf(app.stage as any) : -1;
  const narrative = app ? narrativeFor(app) : null;

  const onStartR1 = async () => {
    if (!app) return;
    setStartingR1(true);
    setStartR1Error(null);
    setTransitionLabel("Connecting you to your Round 1 interview…");
    try {
      // Two-step kickoff:
      //   1. Tell the orchestrator the candidate has joined R1 — this
      //      flips the funnel out of WAITING_CANDIDATE and creates the
      //      InterviewRecord we need for the virtual interview session.
      //   2. Hand the candidate off to the in-app Virtual Interviewer
      //      page (mirrors the existing Xebia virtual-interviewer UX).
      //      That page calls /virtual-interview/start on mount.
      await api.startR1Interview(app.id);
      router.push(`/thrive/virtual-interview/${app.id}`);
    } catch (e: any) {
      setStartR1Error(e.message || String(e));
    } finally {
      setStartingR1(false);
    }
  };

  const onConfirmSlot = async (idx: number, round: "R1" | "R2") => {
    if (!app) return;
    setConfirming(idx);
    setConfirmError(null);
    setTransitionLabel(
      round === "R1"
        ? "Booking your Round 1 interview on Microsoft Teams…"
        : "Booking your Round 2 panel interview on Microsoft Teams…",
    );
    try {
      await api.confirmSlot(app.id, idx, round);
      await refresh();
    } catch (e: any) {
      setConfirmError(e.message || String(e));
      setTransitionLabel(null);
    } finally {
      setConfirming(null);
    }
  };

  // Confirm a CUSTOM R1 start time ("Start now" or a user-picked
  // date/time). Delegates to the confirmCustomR1Slot backend path which
  // appends a 30-minute synthetic slot to proposed_r1_slots and books it.
  const onConfirmCustomR1 = async (startIso: string) => {
    if (!app) return;
    setConfirmError(null);
    setTransitionLabel("Booking your Round 1 interview on Microsoft Teams…");
    try {
      await api.confirmCustomR1Slot(app.id, startIso);
      await refresh();
    } catch (e: any) {
      setConfirmError(e.message || String(e));
      setTransitionLabel(null);
      throw e;
    }
  };

  // Auto-clear the transition overlay once the application's funnel
  // actually advances out of the "waiting_candidate" state — i.e. the
  // orchestrator has finished doing its work and the page is showing
  // the new state. This is the visible signal "we're done processing".
  useEffect(() => {
    if (!transitionLabel || !app) return;
    if (app.agent_status !== "running" && app.agent_status !== "waiting_candidate") {
      setTransitionLabel(null);
    }
    // Special-case: post-confirm we're waiting for stage to flip past
    // "screened"/"r1_done" too — clear the moment we see r1_scheduled
    // / r2_scheduled / waiting_panel.
    if (app.stage === "r1_scheduled" || app.stage === "r2_scheduled") {
      setTransitionLabel(null);
    }
  }, [app?.stage, app?.agent_status, transitionLabel]);

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      {transitionLabel && (
        <div
          role="status"
          aria-live="polite"
          className="sticky top-0 z-40 bg-axis-magenta text-white shadow-card"
        >
          <div className="max-w-5xl mx-auto px-8 py-3 flex items-center gap-3 text-sm font-medium">
            <span
              className="inline-block h-3 w-3 rounded-full border-2 border-white border-t-transparent animate-spin"
              aria-hidden="true"
            />
            <span>{transitionLabel}</span>
            <span className="text-white/70 text-xs">
              Hold tight — this usually takes 3-6 seconds.
            </span>
          </div>
        </div>
      )}
      <main className="flex-1 px-8 py-8 max-w-5xl w-full mx-auto">
        <Link
          href="/thrive"
          className="text-axis-magenta text-xs font-medium hover:underline"
        >
          ← Back to job recommendations
        </Link>

        {/* If the backend no longer knows this application id (typically
            because the in-memory store was wiped by a restart or a demo
            reset), show a clear empty state instead of rendering stale
            React state with dead action buttons. */}
        {appMissing && (
          <div className="mt-6 p-6 bg-axis-pink-soft border border-axis-magenta rounded-card text-sm text-axis-burgundy">
            <p className="font-semibold text-axis-ink">
              This application no longer exists on the server.
            </p>
            <p className="mt-2 text-axis-muted">
              We couldn't find the application{" "}
              <code className="text-axis-ink">{params.appId}</code>. Head
              back to Thrive and apply again to start a fresh one.
            </p>
            <Link
              href="/thrive"
              className="mt-4 inline-block px-4 py-2 rounded bg-axis-magenta text-white text-sm font-semibold hover:bg-axis-burgundy"
            >
              ← Back to Thrive to re-apply
            </Link>
          </div>
        )}

        {error && !appMissing && (
          <div className="mt-6 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            {error}
          </div>
        )}

        {!app && !error && (
          <p className="mt-6 text-sm text-axis-muted">Loading your application…</p>
        )}

        {app && narrative && (
          <>
            {/* ---------- Header card ---------- */}
            <div className="mt-6 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
                    Your application is live
                  </p>
                  <h1 className="text-2xl font-display text-axis-ink mt-1 leading-tight">
                    {job?.title ?? "Loading role…"}
                  </h1>
                  {job && (
                    <p className="text-xs text-axis-muted mt-1">
                      Job ID <strong className="text-axis-ink">{job.job_id}</strong>
                      {" · "}
                      <span className="text-axis-ink">{job.location}</span>
                      {job.band ? (
                        <>
                          {" · "}
                          Band <span className="text-axis-ink">{job.band}</span>
                        </>
                      ) : null}
                      {job.function ? (
                        <>
                          {" · "}
                          <span className="text-axis-ink">{job.function}</span>
                        </>
                      ) : null}
                    </p>
                  )}
                  <p className="text-sm text-axis-muted mt-2">
                    Application reference{" "}
                    <code className="text-axis-ink">{app.id}</code>
                  </p>
                </div>
                {/* Internal status badge intentionally hidden on the
                    candidate view — the timeline + "what's happening
                    now" narrative carries the same information in human
                    language. The badge is still rendered on the
                    Business Partner / Panel / Offer-Team consoles. */}
              </div>

              {/* Progress strip with stage labels */}
              <div className="mt-6">
                <div className="flex items-center gap-2">
                  {STAGE_ORDER.map((s, i) => {
                    const reached = app.stage === "rejected" ? false : i <= stageIdx;
                    const active = i === stageIdx && app.stage !== "rejected";
                    return (
                      <div key={s} className="flex-1 flex items-center">
                        <div
                          className={`h-2 flex-1 rounded ${
                            reached ? "bg-axis-magenta" : "bg-axis-divider"
                          } ${active ? "ring-2 ring-axis-magenta/40" : ""}`}
                        />
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 flex justify-between text-[10px] text-axis-muted">
                  {STAGE_ORDER.map((s, i) => (
                    <span
                      key={s}
                      className={`flex-1 text-center ${
                        i === stageIdx && app.stage !== "rejected"
                          ? "text-axis-magenta font-semibold"
                          : ""
                      }`}
                    >
                      {STAGE_LABEL[s]}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* ---------- Candidate-facing status card ----------
                Warm, human copy. We intentionally do NOT show any
                match percentage, rubric, matched/missing skill chips,
                or "AI screening" language to the candidate — that's
                an internal HR signal only. */}
            {app.stage !== "applied" && app.candidate_kind !== "external" && (
              <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-5">
                <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
                  Your application
                </p>
                <h2 className="text-base font-semibold text-axis-ink mt-1">
                  Thanks for applying — we've received your profile
                </h2>
                <p className="text-sm text-axis-ink-soft mt-3 leading-relaxed">
                  Our team has reviewed your background against this role.
                  {app.match_percent >= 75
                    ? " We'd love to move forward — please pick an interview slot below and we'll see you soon."
                    : " We appreciate the time you took to apply. For this particular role we've decided to move ahead with other candidates, but we'll keep your profile on file for roles that are a closer fit."}
                </p>
              </div>
            )}

            {/* ---------- Level 1 framing for external candidates ----------
                External candidates skip the rubric screening and the
                generic "now / next" narrative. They get a dedicated
                Level 1 — AI Agent Interview header that makes it
                explicit what the next step is. */}
            {app.candidate_kind === "external" &&
              (app.stage === "applied" || app.stage === "screened") && (
                <div
                  className="mt-4 rounded-card p-5 text-white shadow-card"
                  style={{
                    background:
                      "linear-gradient(135deg, #6b2566 0%, #4a1e47 100%)",
                  }}
                >
                  <p className="text-[10px] uppercase tracking-widest text-white/70 font-bold">
                    Level 1 · Axis AI Interview
                  </p>
                  <h2 className="text-xl font-display mt-1">
                    {app.agent_status === "waiting_hr"
                      ? "We couldn't find a common Round 1 slot — your Business Partner has been notified"
                      : app.proposed_r1_slots && app.proposed_r1_slots.length > 0
                      ? "Pick a time for your Round 1 interview"
                      : "Getting your Round 1 interview times ready…"}
                  </h2>
                  <p className="text-sm text-white/80 mt-2 leading-relaxed">
                    {app.agent_status === "waiting_hr"
                      ? (app.next_action ||
                          "We couldn't find a common Round 1 slot in the next 5 business days. Your Business Partner has been notified and will free up time on the panel calendar — this page will refresh automatically once new times are available.")
                      : app.proposed_r1_slots && app.proposed_r1_slots.length > 0
                      ? "Your Round 1 interview is a conversational AI interview. Pick one of the times below — you'll join on Microsoft Teams, answer a few role-related questions out loud, and we'll share your result on this page shortly after. No human panellists at this stage."
                      : "Your Round 1 interview is a conversational AI interview. We're checking calendars to suggest times that work — this usually takes a few seconds. The page will refresh automatically."}
                  </p>
                </div>
              )}

            {/* ---------- Guided "now / next" card ---------- */}
            <div
              className={`mt-4 rounded-card border p-5 ${
                app.candidate_kind === "external" &&
                (app.stage === "applied" || app.stage === "screened")
                  ? "hidden"
                  : ""
              } ${
                narrative.tone === "danger"
                  ? "bg-axis-pink-soft border-axis-magenta"
                  : narrative.tone === "success"
                  ? "bg-axis-cream border-axis-cream-border"
                  : narrative.tone === "action"
                  ? "bg-axis-cream border-axis-cream-border"
                  : "bg-axis-surface border-axis-divider"
              }`}
            >
              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
                    What's happening now
                  </p>
                  <p className="text-sm text-axis-ink mt-1 leading-relaxed">
                    {narrative.now}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
                    What happens next
                  </p>
                  <p className="text-sm text-axis-ink-soft mt-1 leading-relaxed">
                    {narrative.next}
                  </p>
                </div>
              </div>
            </div>

            {/* ---------- R1 slot picker — only BEFORE the meeting is booked.
                Once stage advances past `screened`, R1 has been booked and
                the SlotPickerCard becomes wrong (the screenshot bug). The
                BookedInterviewCard takes over from here. ---------- */}
            {app.stage === "screened" &&
              app.agent_status === "waiting_candidate" &&
              app.proposed_r1_slots.length > 0 && (
                <SlotPickerCard
                  round="R1"
                  slots={app.proposed_r1_slots}
                  selectedIdx={pendingR1Slot}
                  onSelect={(i) => {
                    setConfirmError(null);
                    setPendingR1Slot(i);
                  }}
                  onClear={() => setPendingR1Slot(null)}
                  title={
                    app.candidate_kind === "external"
                      ? "Start your Level 1 interview"
                      : "Start your Round 1 interview"
                  }
                  subtitle={
                    "Your Round 1 interview is a conversational AI interview, so you can start right now or schedule a 30-minute slot at any date and time that suits you. Nothing is booked until you confirm."
                  }
                  error={confirmError}
                  onPickCustomR1={(mode, iso) => {
                    setConfirmError(null);
                    setCustomR1Mode(mode);
                    if (mode === "now") {
                      // "Start now" → lock to current wall clock at
                      // confirm time. We stage a sentinel "now" here
                      // and resolve to a real ISO at confirm-click so
                      // the backend books at actual `Date.now()`.
                      setPendingCustomR1Start("now");
                    } else if (iso) {
                      setPendingCustomR1Start(iso);
                    }
                  }}
                />
              )}

            {/* ---------- "Round 1 scheduled" card — once R1 is booked.
                Shows the actual date/time, Teams join URL, and a
                Reschedule button (disabled within 4h of the meeting).
                Hidden once the candidate has started R1 — at that
                point we no longer want to show "your interview is booked"
                copy; the page is now about the result of the interview,
                not the calendar slot. */}
            {app.stage === "r1_scheduled" && !app.r1_started && (
              <BookedInterviewCard
                round="R1"
                interview={app.interviews.find((i) => i.round === "R1") ?? null}
                onReschedule={() => {
                  setRescheduleError(null);
                  setPendingReschedule("R1");
                }}
                error={rescheduleError && pendingReschedule === null ? rescheduleError : null}
              />
            )}

            {/* ---------- Round 1 post-start card.
                Two sub-states:
                  (a) Candidate finished the conversation → "scoring in
                      progress" with spinner (transcript captured, waiting
                      for scorer to advance the funnel).
                  (b) Candidate started but bailed mid-flow (closed tab,
                      clicked back) → show a "Resume your interview" CTA
                      so they aren't stranded.
                We detect (a) vs (b) by looking at whether the R1
                InterviewRecord has any transcript segments yet. */}
            {app.stage === "r1_scheduled" && app.r1_started && (() => {
              const r1 = app.interviews.find((i) => i.round === "R1");
              const hasTranscript = !!(r1 && Array.isArray(r1.transcript) && r1.transcript.length > 0);
              if (hasTranscript) {
                return (
                  <div className="mt-4 bg-axis-canvas border-2 border-axis-magenta rounded-card p-5">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase tracking-wider bg-axis-magenta text-white font-semibold px-2 py-0.5 rounded">
                        Round 1 finished
                      </span>
                      <span className="text-[10px] uppercase tracking-wider text-axis-muted">
                        Scoring in progress
                      </span>
                    </div>
                    <h2 className="text-lg font-semibold text-axis-ink mt-2">
                      Your Round 1 interview is complete — results coming
                    </h2>
                    <p className="text-xs text-axis-muted mt-1 max-w-2xl">
                      Thanks for finishing your Round 1 conversation. We're
                      reviewing your answers right now — this usually takes
                      only a few seconds. Your result and next step will
                      appear on this page automatically.
                    </p>
                    <div className="mt-4 flex items-center gap-3">
                      <span
                        className="inline-block h-3 w-3 rounded-full border-2 border-axis-magenta border-t-transparent animate-spin"
                        aria-hidden
                      />
                      <span className="text-xs text-axis-magenta font-semibold">
                        Scoring your Round 1 answers…
                      </span>
                    </div>
                  </div>
                );
              }
              // Incomplete — candidate navigated away mid-interview.
              return (
                <div className="mt-4 bg-axis-canvas border-2 border-amber-400 rounded-card p-5">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] uppercase tracking-wider bg-amber-500 text-white font-semibold px-2 py-0.5 rounded">
                      Interview paused
                    </span>
                    <span className="text-[10px] uppercase tracking-wider text-axis-muted">
                      Resume when ready
                    </span>
                  </div>
                  <h2 className="text-lg font-semibold text-axis-ink mt-2">
                    Looks like your Round 1 was interrupted
                  </h2>
                  <p className="text-xs text-axis-muted mt-1 max-w-2xl">
                    No problem — your session is still live. Click below
                    to pick up where you left off. A fresh set of questions
                    will start and your earlier answers (if any) are safe.
                  </p>
                  <div className="mt-4 flex items-center gap-3">
                    <button
                      onClick={() => router.push(`/thrive/virtual-interview/${app.id}`)}
                      className="px-4 py-2 bg-axis-magenta text-white text-sm font-semibold rounded-lg hover:bg-axis-burgundy transition-colors"
                    >
                      Resume interview
                    </button>
                    <span className="text-[11px] text-axis-muted">
                      Make sure your camera + microphone are ready.
                    </span>
                  </div>
                </div>
              );
            })()}

            {/* ---------- Round 1 result + next step.
                Shown once the funnel has actually advanced past R1 —
                either to R1_DONE (cleared) or REJECTED (auto-closed). */}
            {(app.stage === "r1_done" ||
              app.stage === "r2_scheduled" ||
              app.stage === "offer_negotiation" ||
              app.stage === "offer") && (
              <div className="mt-4 bg-axis-canvas border-2 border-emerald-500/60 rounded-card p-5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider bg-emerald-600 text-white font-semibold px-2 py-0.5 rounded">
                    Round 1 Completed
                  </span>
                </div>
                <h2 className="text-lg font-semibold text-axis-ink mt-2">
                We have recorded Round 1 answers and are now preparing for your Round 2 panel interview.
                </h2>
                <p className="text-xs text-axis-muted mt-1 max-w-2xl">
                Our team would get back to you with next steps.
                </p>
              </div>
            )}

            {/* ---------- Round 2 cleared — shown once panel has cleared the candidate. */}
            {(app.stage === "offer_negotiation" || app.stage === "offer") && (
              <div className="mt-4 bg-axis-canvas border-2 border-emerald-500/60 rounded-card p-5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider bg-emerald-600 text-white font-semibold px-2 py-0.5 rounded">
                    Round 2 cleared
                  </span>
                </div>
                <h2 className="text-lg font-semibold text-axis-ink mt-2">
                  You've cleared Round 2 🎉
                </h2>
                <p className="text-xs text-axis-muted mt-1 max-w-2xl">
                  The panel has shared positive feedback on your Round 2
                  interview. We're now moving to the offer stage — your
                  Business Partner will be in touch shortly.
                </p>
              </div>
            )}

            {/* ---------- Offer Accept / Decline action card ---------- */}
            {app.stage === "offer" && app.agent_status === "waiting_candidate_acceptance" && (
              <div className="mt-4 bg-white border-2 border-emerald-500/60 rounded-xl shadow-lg overflow-hidden">
                <div className="h-1.5 bg-gradient-to-r from-emerald-500 to-axis-magenta" />
                <div className="p-6">
                  <h2 className="text-lg font-semibold text-axis-ink mb-1">
                    Accept your offer & start your journey
                  </h2>
                  <p className="text-sm text-axis-muted mb-6">
                    We're excited to have you join Axis Bank! Please share a few details so we can start your personalised onboarding experience.
                  </p>

                  {offerError && (
                    <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                      {offerError}
                    </div>
                  )}

                  {!showDeclineForm ? (
                    <div className="space-y-4">
                      {/* Phone */}
                      <div>
                        <label className="block text-sm font-medium text-axis-ink mb-1">
                          WhatsApp number <span className="text-axis-muted font-normal">(for onboarding updates)</span>
                        </label>
                        <input
                          type="tel"
                          placeholder="+91 98765 43210"
                          value={offerPhone}
                          onChange={(e) => setOfferPhone(e.target.value)}
                          className="w-full border border-axis-divider rounded-lg px-4 py-2.5 text-sm text-axis-ink placeholder:text-axis-muted/50 focus:border-axis-magenta focus:ring-1 focus:ring-axis-magenta outline-none"
                        />
                      </div>

                      {/* Joining date */}
                      <div>
                        <label className="block text-sm font-medium text-axis-ink mb-1">
                          Expected joining date
                        </label>
                        <input
                          type="date"
                          value={offerJoiningDate}
                          onChange={(e) => setOfferJoiningDate(e.target.value)}
                          className="w-full border border-axis-divider rounded-lg px-4 py-2.5 text-sm text-axis-ink focus:border-axis-magenta focus:ring-1 focus:ring-axis-magenta outline-none"
                        />
                      </div>

                      {/* WhatsApp consent */}
                      <label className="flex items-start gap-3 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={offerConsent}
                          onChange={(e) => setOfferConsent(e.target.checked)}
                          className="mt-0.5 h-4 w-4 rounded border-axis-divider text-axis-magenta focus:ring-axis-magenta"
                        />
                        <span className="text-sm text-axis-muted">
                          I'd like to receive onboarding updates via WhatsApp. You'll get helpful reminders about documents, team introductions, and your joining day.
                        </span>
                      </label>

                      {/* Action buttons */}
                      <div className="flex items-center gap-3 pt-2">
                        <button
                          onClick={async () => {
                            if (!offerPhone.trim()) {
                              setOfferError("Please enter your WhatsApp number");
                              return;
                            }
                            if (!offerJoiningDate) {
                              setOfferError("Please select your expected joining date");
                              return;
                            }
                            setOfferSubmitting(true);
                            setOfferError(null);
                            try {
                              await acceptOffer(app.id, offerPhone.trim(), offerConsent, offerJoiningDate);
                              refresh();
                            } catch (e: any) {
                              setOfferError(e.message || "Failed to accept offer");
                            } finally {
                              setOfferSubmitting(false);
                            }
                          }}
                          disabled={offerSubmitting}
                          className="px-8 py-3 bg-emerald-600 text-white font-semibold rounded-lg hover:bg-emerald-700 transition-colors shadow-md text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {offerSubmitting ? "Accepting\u2026" : "Accept Offer"}
                        </button>
                        <button
                          onClick={() => setShowDeclineForm(true)}
                          className="px-6 py-3 text-axis-muted text-sm hover:text-red-600 transition-colors"
                        >
                          I need to decline
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <p className="text-sm text-axis-ink">
                        We're sorry to see you go. Could you share why so we can improve?
                      </p>
                      <textarea
                        value={declineReason}
                        onChange={(e) => setDeclineReason(e.target.value)}
                        placeholder="Your reason (optional)"
                        rows={3}
                        className="w-full border border-axis-divider rounded-lg px-4 py-2.5 text-sm text-axis-ink placeholder:text-axis-muted/50 focus:border-axis-magenta focus:ring-1 focus:ring-axis-magenta outline-none resize-none"
                      />
                      <div className="flex items-center gap-3">
                        <button
                          onClick={async () => {
                            setOfferSubmitting(true);
                            setOfferError(null);
                            try {
                              await declineOffer(app.id, declineReason || undefined);
                              refresh();
                            } catch (e: any) {
                              setOfferError(e.message || "Failed to decline offer");
                            } finally {
                              setOfferSubmitting(false);
                            }
                          }}
                          disabled={offerSubmitting}
                          className="px-6 py-2.5 bg-red-600 text-white font-semibold rounded-lg hover:bg-red-700 transition-colors text-sm disabled:opacity-50"
                        >
                          {offerSubmitting ? "Processing\u2026" : "Confirm Decline"}
                        </button>
                        <button
                          onClick={() => { setShowDeclineForm(false); setDeclineReason(""); }}
                          className="px-6 py-2.5 text-axis-muted text-sm hover:text-axis-ink transition-colors"
                        >
                          Go back
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ---------- Engagement Journey Timeline ---------- */}
            {(app.stage === "offer_accepted" || app.stage === "pre_joining") && engagementJourney && (
              <div className="mt-4 bg-white border border-axis-divider rounded-xl shadow overflow-hidden">
                <div className="h-1 bg-gradient-to-r from-axis-burgundy to-axis-magenta" />
                <button
                  type="button"
                  onClick={() => setJourneyExpanded((v) => !v)}
                  className="w-full flex items-center justify-between gap-3 px-6 py-4 text-left hover:bg-axis-surface/40 transition-colors"
                  aria-expanded={journeyExpanded}
                >
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold text-axis-ink">
                      Your Onboarding Journey
                    </h2>
                    <p className="text-sm text-axis-muted mt-0.5 truncate">
                      {(() => {
                        const done = engagementJourney.touchpoints.filter(
                          (t: EngagementTouchpoint) => t.status === "sent" || t.status === "delivered" || t.status === "read"
                        ).length;
                        const total = engagementJourney.touchpoints.length;
                        const joining = engagementJourney.expected_joining_date
                          ? new Date(engagementJourney.expected_joining_date).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })
                          : null;
                        return (
                          <>
                            {done}/{total} touchpoints complete
                            {joining ? <> · Joining {joining}</> : null}
                          </>
                        );
                      })()}
                    </p>
                  </div>
                  <span className="text-axis-muted text-xs font-medium flex items-center gap-1 shrink-0">
                    {journeyExpanded ? "Hide" : "Show"}
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      className={`w-4 h-4 transition-transform ${journeyExpanded ? "rotate-180" : ""}`}
                    >
                      <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z" clipRule="evenodd" />
                    </svg>
                  </span>
                </button>
                {journeyExpanded && (
                <div className="px-6 pb-6">
                  <p className="text-sm text-axis-muted mb-4">
                    Here's what's coming up as you prepare to join Axis Bank.
                    {engagementJourney.expected_joining_date && (
                      <> Your joining date: <span className="font-semibold text-axis-ink">{new Date(engagementJourney.expected_joining_date).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}</span></>
                    )}
                  </p>

                  <div className="space-y-0">
                    {engagementJourney.touchpoints.map((tp: EngagementTouchpoint, idx: number) => {
                      const isCompleted = tp.status === "sent" || tp.status === "delivered" || tp.status === "read";
                      const isPending = tp.status === "pending";
                      const isFailed = tp.status === "failed";
                      const isSkipped = tp.status === "skipped";

                      const kindLabels: Record<string, string> = {
                        welcome_whatsapp: "Welcome message",
                        buddy_intro: "Meet your buddy",
                        document_checklist: "Document checklist",
                        culture_video: "Life at Axis Bank",
                        employee_stories: "Stories from your future colleagues",
                        benefits_overview: "Your benefits at Axis",
                        weekly_checkin: "Weekly check-in",
                        linkedin_connect: "Connect with your team",
                        it_setup_form: "IT setup & access",
                        team_intro_call: "Virtual coffee with the team",
                        dress_code_tips: "Day 1 tips & what to wear",
                        joining_reminder: "Joining day reminder",
                        day_one_welcome: "Day 1 welcome",
                        custom: "Custom touchpoint",
                      };

                      return (
                        <div key={tp.id} className="flex gap-4">
                          {/* Timeline line + dot */}
                          <div className="flex flex-col items-center">
                            <div className={`w-3 h-3 rounded-full border-2 mt-1 ${
                              isCompleted ? "bg-emerald-500 border-emerald-500" :
                              isFailed ? "bg-red-500 border-red-500" :
                              isSkipped ? "bg-gray-300 border-gray-300" :
                              "bg-white border-axis-divider"
                            }`} />
                            {idx < engagementJourney.touchpoints.length - 1 && (
                              <div className={`w-0.5 flex-1 min-h-[24px] ${
                                isCompleted ? "bg-emerald-300" : "bg-axis-divider"
                              }`} />
                            )}
                          </div>

                          {/* Content */}
                          <div className="pb-4 flex-1">
                            <div className="flex items-center gap-2">
                              <span className={`text-sm font-medium ${
                                isCompleted ? "text-emerald-700" :
                                isFailed ? "text-red-600" :
                                isSkipped ? "text-gray-400 line-through" :
                                "text-axis-ink"
                              }`}>
                                {kindLabels[tp.kind] || tp.kind}
                              </span>
                              {isCompleted && (
                                <span className="text-[10px] px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded font-medium">
                                  {tp.status === "read" ? "Read" : tp.status === "delivered" ? "Delivered" : "Sent"}
                                </span>
                              )}
                              {isFailed && (
                                <span className="text-[10px] px-1.5 py-0.5 bg-red-100 text-red-600 rounded font-medium">
                                  Failed
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-axis-muted mt-0.5">
                              {new Date(tp.scheduled_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                              {tp.candidate_response && (
                                <span className="ml-2 text-axis-ink">You replied: &ldquo;{tp.candidate_response}&rdquo;</span>
                              )}
                            </p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
                )}
              </div>
            )}

            {/* ---------- Onboarding Assistant (candidate chatbot) ---------- */}
            {(app.stage === "offer_accepted" || app.stage === "pre_joining") && (
              <div className="mt-4 bg-white border border-axis-divider rounded-xl shadow overflow-hidden">
                <div className="h-1 bg-gradient-to-r from-axis-magenta to-axis-burgundy" />
                <div className="p-6">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold text-axis-ink">
                        Ask the Onboarding Team
                      </h2>
                      <p className="text-sm text-axis-muted mt-0.5">
                        Got a question about culture, travel, leave, benefits
                        or your role? Ask here — we&apos;ll answer in the
                        context of your role
                        {job?.title ? <> ({job.title})</> : null}. The
                        conversation is shared with your onboarding SPOC.
                      </p>
                    </div>
                  </div>

                  {/* Transcript */}
                  <div className="mt-4 max-h-80 overflow-y-auto space-y-3 bg-axis-surface border border-axis-divider rounded-lg p-4">
                    {chatMessages.length === 0 && !chatSending && (
                      <div className="text-center text-xs text-axis-muted py-6">
                        <p>No messages yet. Try one of these to start:</p>
                        <div className="mt-3 flex flex-wrap justify-center gap-2">
                          {[
                            "What's the culture at Axis like?",
                            "What's the travel policy for my band?",
                            "How does mobile and internet reimbursement work?",
                            "How many leaves do I get?",
                            "What does my role involve day-to-day?",
                            "What documents do I need on Day 1?",
                          ].map((q) => (
                            <button
                              key={q}
                              type="button"
                              onClick={() => setChatInput(q)}
                              className="px-2.5 py-1 text-[11px] rounded-full bg-white border border-axis-divider hover:border-axis-burgundy hover:text-axis-burgundy text-axis-ink transition-colors"
                            >
                              {q}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {chatMessages.map((m) => {
                      const isUser = m.direction === "inbound";
                      return (
                        <div
                          key={m.id}
                          className={`flex ${isUser ? "justify-end" : "justify-start"}`}
                        >
                          <div
                            className={`max-w-[80%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                              isUser
                                ? "bg-axis-burgundy text-white rounded-br-sm"
                                : "bg-white border border-axis-divider text-axis-ink rounded-bl-sm"
                            }`}
                          >
                            {!isUser && (
                              <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold mb-1">
                                Onboarding Team
                              </p>
                            )}
                            <p className="leading-relaxed">{m.body}</p>
                            {m.status === "sending" && (
                              <p className="text-[10px] opacity-70 mt-1">Sending…</p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    {chatSending && (
                      <div className="flex justify-start">
                        <div className="bg-white border border-axis-divider text-axis-muted rounded-lg rounded-bl-sm px-3 py-2 text-sm">
                          <span className="inline-flex items-center gap-1">
                            <span className="w-1.5 h-1.5 bg-axis-magenta rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                            <span className="w-1.5 h-1.5 bg-axis-magenta rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                            <span className="w-1.5 h-1.5 bg-axis-magenta rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                            <span className="ml-2 text-xs">Looking it up for you…</span>
                          </span>
                        </div>
                      </div>
                    )}
                  </div>

                  {chatError && (
                    <p className="mt-2 text-xs text-red-600">{chatError}</p>
                  )}

                  {/* Input */}
                  <div className="mt-3 flex gap-2">
                    <input
                      type="text"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          onSendChat();
                        }
                      }}
                      placeholder="Ask about culture, travel, reimbursement, leave, your role…"
                      className="flex-1 border border-axis-divider rounded-lg px-3 py-2 text-sm focus:border-axis-burgundy focus:outline-none"
                      disabled={chatSending}
                    />
                    <button
                      type="button"
                      onClick={onSendChat}
                      disabled={chatSending || !chatInput.trim()}
                      className="px-5 py-2 bg-axis-burgundy text-white font-semibold text-sm rounded-lg hover:bg-axis-burgundy-dark disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                    >
                      {chatSending ? "Sending…" : "Send"}
                    </button>
                  </div>
                  <p className="mt-2 text-[10px] text-axis-muted-light">
                    Your onboarding team can see this conversation and will
                    follow up if anything needs a human touch.
                  </p>
                </div>
              </div>
            )}

            {app.stage === "rejected" && app.r1_started && (
              <div className="mt-4 bg-axis-canvas border-2 border-axis-burgundy rounded-card p-5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider bg-axis-burgundy text-white font-semibold px-2 py-0.5 rounded">
                    Round 1 closed
                  </span>
                </div>
                <h2 className="text-lg font-semibold text-axis-ink mt-2">
                  Your Round 1 result
                </h2>
                <p className="text-xs text-axis-muted mt-1 max-w-2xl">
                  Thanks for taking the time to interview with us. Based
                  on your Round 1 answers we won't be progressing this
                  application further for this role. You're welcome to
                  apply for other open roles on Thrive any time.
                </p>
                <Link
                  href="/thrive"
                  className="mt-4 inline-block px-4 py-2 rounded bg-axis-magenta text-white text-xs font-semibold hover:bg-axis-burgundy"
                >
                  Browse other open roles →
                </Link>
              </div>
            )}

            {/* ---------- R2 slot picker (only when WAITING_CANDIDATE @ R1_DONE) ---------- */}
            {app.stage === "r1_done" &&
              app.agent_status === "waiting_candidate" &&
              app.proposed_r2_slots.length > 0 && (
                <SlotPickerCard
                  round="R2"
                  slots={app.proposed_r2_slots}
                  selectedIdx={pendingR2Slot}
                  onSelect={(i) => {
                    setConfirmError(null);
                    setPendingR2Slot(i);
                  }}
                  onClear={() => setPendingR2Slot(null)}
                  title="Pick your Round 2 panel interview time"
                  subtitle="We've checked your availability against your Business Partner's and every panel member's calendar. The 3 times below are the only ones that work for everyone in the next 5 business days. Tap a tile to select — you'll review and confirm before your panel Teams meeting is created."
                  error={confirmError}
                />
              )}

            {/* ---------- "Round 2 scheduled" card — once R2 is booked. */}
            {app.stage === "r2_scheduled" && (
              <BookedInterviewCard
                round="R2"
                interview={app.interviews.find((i) => i.round === "R2") ?? null}
                onReschedule={() => {
                  setRescheduleError(null);
                  setPendingReschedule("R2");
                }}
                error={rescheduleError && pendingReschedule === null ? rescheduleError : null}
              />
            )}

            {/* ---------- Start R1 interview CTA ---------- */}
            {app.stage === "r1_scheduled" && !app.r1_started && (
              <div className="mt-4 bg-axis-canvas border-2 border-axis-magenta rounded-card p-5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider bg-axis-magenta text-white font-semibold px-2 py-0.5 rounded">
                    Action needed from you
                  </span>
                </div>
                <h2 className="text-base font-semibold text-axis-ink mt-2">
                  Start your Round 1 interview
                </h2>
                <p className="text-xs text-axis-muted mt-1 max-w-2xl">
                  Your Teams meeting is on your calendar (and your Business Partner's).
                  When you click below, you'll begin a short conversational
                  interview with a few role-related questions. We'll share
                  your result on this page shortly after you finish.
                </p>
                {startR1Error && (
                  <div className="mt-3 p-2 rounded bg-axis-pink-soft border border-axis-magenta text-xs text-axis-burgundy">
                    {startR1Error}
                  </div>
                )}
                <button
                  onClick={() => {
                    setStartR1Error(null);
                    setPendingStartR1(true);
                  }}
                  disabled={startingR1}
                  className="mt-4 bg-axis-magenta text-white text-sm font-semibold px-5 py-2.5 rounded shadow-card hover:bg-axis-burgundy transition disabled:opacity-50 disabled:cursor-wait"
                >
                  {startingR1 ? "Starting your interview…" : "Start my Round 1 interview →"}
                </button>
              </div>
            )}

            {/* ---------- R1 AI Interview report ----------
                CONFIDENTIAL: this report (headline, score, recommendation,
                rubric, transcript highlights) is the AI Interview Agent's
                internal memo for the Business Partner and the R2 panel. It is
                never shown on the candidate-facing /thrive/status page.
                The candidate only sees the high-level "you cleared R1 /
                R1 closed" outcome card above. */}

            {/* ---------- Live activity feed ----------
                HIDDEN on the candidate-facing page: this trace of
                "agent did X, agent did Y" is an internal debugging view
                for Business Partners / Ops and is not appropriate for
                the candidate experience. The page already polls via
                useAutoRefresh, so candidates still see their status
                update live without needing a raw activity log. */}
          </>
        )}
      </main>
      <Footer />

      {/* ----- Confirm dialogs (mounted once at the root) ----- */}
      <ConfirmDialog
        open={pendingR1Slot !== null && !!app}
        title="Confirm your Round 1 interview slot"
        message={
          pendingR1Slot !== null && app ? (
            <>
              You're about to book{" "}
              <strong className="text-axis-ink">
                {formatSlotLong(app.proposed_r1_slots[pendingR1Slot])}
              </strong>{" "}
              for your Round 1 interview. This will create a real Microsoft
              Teams meeting on your calendar and on your Business Partner's
              calendar.
            </>
          ) : (
            ""
          )
        }
        consequences={[
          "A Teams calendar invite is sent to you and your Business Partner immediately.",
          "The other two proposed slots are released back to your Business Partner.",
          "You can still reschedule later by replying to the invite.",
        ]}
        confirmLabel="Confirm and book"
        onConfirm={async () => {
          if (pendingR1Slot === null) return;
          await onConfirmSlot(pendingR1Slot, "R1");
          setPendingR1Slot(null);
        }}
        onCancel={() => setPendingR1Slot(null)}
      />

      {/* Custom R1 start (Start now / user-picked date & time). */}
      <ConfirmDialog
        open={pendingCustomR1Start !== null && !!app}
        title={
          customR1Mode === "now"
            ? "Start your Round 1 interview now?"
            : "Confirm your Round 1 interview time"
        }
        message={
          pendingCustomR1Start !== null && app ? (
            customR1Mode === "now" ? (
              <>
                You're about to start your Round 1 interview right now.
                You'll be taken straight into the interview page and the
                first question will begin once your camera and microphone
                are ready.
              </>
            ) : (
              <>
                You're about to book your Round 1 interview for{" "}
                <strong className="text-axis-ink">
                  {new Date(pendingCustomR1Start).toLocaleString(undefined, {
                    weekday: "long",
                    day: "numeric",
                    month: "long",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </strong>
                . This is a 30-minute slot and a Microsoft Teams meeting
                will be created on your calendar.
              </>
            )
          ) : (
            ""
          )
        }
        consequences={
          customR1Mode === "now"
            ? [
                "A Microsoft Teams meeting is created on your calendar immediately.",
                "You'll be redirected to the live interview page to begin.",
                "Your responses will be reviewed and your Round 1 result will appear on this page shortly after.",
              ]
            : [
                "A Microsoft Teams calendar invite is sent to you for the time you picked.",
                "The 30-minute slot starts at the exact time you selected.",
                "You can reschedule later up to 4 hours before the meeting.",
              ]
        }
        confirmLabel={
          customR1Mode === "now" ? "Start now" : "Confirm and book"
        }
        onConfirm={async () => {
          if (pendingCustomR1Start === null) return;
          try {
            // Resolve "now" sentinel to a real ISO at click time so we
            // book at the actual current wall clock.
            const iso =
              pendingCustomR1Start === "now"
                ? new Date().toISOString()
                : pendingCustomR1Start;
            await onConfirmCustomR1(iso);
            setPendingCustomR1Start(null);
          } catch {
            // Error already surfaced via setConfirmError / throw in
            // onConfirmCustomR1. Keep the dialog open so the user can
            // retry or cancel.
          }
        }}
        onCancel={() => setPendingCustomR1Start(null)}
      />

      <ConfirmDialog
        open={pendingR2Slot !== null && !!app}
        title="Confirm your Round 2 panel interview slot"
        message={
          pendingR2Slot !== null && app ? (
            <>
              You're about to book{" "}
              <strong className="text-axis-ink">
                {formatSlotLong(app.proposed_r2_slots[pendingR2Slot])}
              </strong>{" "}
              for your Round 2 panel interview. This will create a real
              Microsoft Teams meeting on every panellist's calendar.
            </>
          ) : (
            ""
          )
        }
        consequences={[
          "A Teams calendar invite is sent to you, your Business Partner and every panel member.",
          "The panel will receive your Round 1 AI interview report ahead of the meeting.",
          "Reschedule requests can be made via the calendar invite.",
        ]}
        confirmLabel="Confirm and book"
        onConfirm={async () => {
          if (pendingR2Slot === null) return;
          await onConfirmSlot(pendingR2Slot, "R2");
          setPendingR2Slot(null);
        }}
        onCancel={() => setPendingR2Slot(null)}
      />

      <ConfirmDialog
        open={pendingReschedule !== null}
        title={
          pendingReschedule === "R1"
            ? "Reschedule your Round 1 interview?"
            : "Reschedule your Round 2 panel interview?"
        }
        message={
          <>
            Confirming will <strong>cancel the current Microsoft Teams meeting</strong>{" "}
            on every attendee's calendar and we'll propose 3 fresh times
            that work for everyone. You'll then pick a new time the same
            way you did the first time.
            <br />
            <br />
            <span className="text-axis-burgundy">
              <strong>Cutoff:</strong> reschedules are only allowed up to{" "}
              <strong>4 hours</strong> before the meeting starts. After that
              you'll need to contact your Business Partner directly.
            </span>
          </>
        }
        consequences={[
          "The existing Teams meeting is cancelled on every attendee's calendar (you, your Business Partner and — for R2 — every panellist).",
          "We re-check everyone's availability in real time before proposing new times.",
          "Your application stays on track — only the meeting is replaced.",
        ]}
        confirmLabel="Cancel meeting and propose new slots"
        tone="danger"
        onConfirm={async () => {
          if (!app || !pendingReschedule) return;
          try {
            await api.rescheduleInterview(app.id, pendingReschedule);
            await refresh();
            setPendingReschedule(null);
          } catch (e: any) {
            // Surface the 4-hour cutoff message inline so the candidate
            // sees exactly why the request was refused.
            setRescheduleError(e?.message || String(e));
            setPendingReschedule(null);
          }
        }}
        onCancel={() => setPendingReschedule(null)}
      />

      <ConfirmDialog
        open={pendingStartR1}
        title="Start your Round 1 interview"
        message={
          <>
            You're about to start your Round 1 interview. You'll answer a few
            role-related questions out loud, and we'll share your result on
            this page shortly after you finish.
          </>
        }
        consequences={[
          "Your responses and result are shared with your Business Partner.",
          "Your application will pause for your Business Partner to confirm the panel for Round 2.",
          "You can review your status on this page at any time.",
        ]}
        confirmLabel="Run Round 1 now"
        onConfirm={async () => {
          await onStartR1();
          setPendingStartR1(false);
        }}
        onCancel={() => setPendingStartR1(false)}
      />
    </div>
  );
}

/**
 * Pretty long-form formatter used inside the confirm dialogs:
 * "Tuesday, 07 April 2026 · 09:00–09:30 IST".
 */
function formatSlotLong(slot: { start: string; end: string }): string {
  const start = new Date(slot.start);
  const end = new Date(slot.end);
  const date = start.toLocaleDateString(undefined, {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
  const t = (d: Date) =>
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `${date} · ${t(start)}–${t(end)} IST`;
}

/**
 * Self-contained slot picker tile grid.
 *
 * Behaviour: tiles are *radio buttons*, not action buttons. Tapping a tile
 * highlights it (selectedIdx) but DOES NOT trigger any side effect. The
 * parent component is responsible for opening the ConfirmDialog when
 * selectedIdx changes from null. The user may also re-select a different
 * tile or hit Cancel inside the dialog without losing their place.
 */
function SlotPickerCard({
  round,
  slots,
  selectedIdx,
  onSelect,
  onClear,
  title,
  subtitle,
  error,
  onPickCustomR1,
}: {
  round: "R1" | "R2";
  slots: { start: string; end: string }[];
  selectedIdx: number | null;
  onSelect: (idx: number) => void;
  onClear: () => void;
  title: string;
  subtitle: string;
  error: string | null;
  /**
   * Optional: for R1 only, a callback that opens the custom-start confirm
   * dialog with the chosen ISO datetime. `"now"` means "start immediately",
   * any other string is a user-picked ISO datetime from the date/time input.
   * When undefined, the Start-now / schedule-later panel is hidden.
   */
  onPickCustomR1?: (mode: "now" | "later", isoOrNull: string | null) => void;
}) {
  // Local state for the R1 date/time picker (user-picked "later" option).
  const [laterDate, setLaterDate] = useState<string>(() => {
    // Default to tomorrow 10:00 in the user's local TZ.
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(10, 0, 0, 0);
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  });
  return (
    <div className="mt-4 bg-axis-canvas border-2 border-axis-magenta rounded-card p-5">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider bg-axis-magenta text-white font-semibold px-2 py-0.5 rounded">
          Action needed from you
        </span>
        <span className="text-[10px] uppercase tracking-wider text-axis-muted">
          Step · {round === "R1" ? "Schedule Round 1" : "Schedule Round 2"}
        </span>
      </div>
      <h2 className="text-base font-semibold text-axis-ink mt-2">{title}</h2>
      <p className="text-xs text-axis-muted mt-1 max-w-3xl">{subtitle}</p>

      {error && (
        <div className="mt-3 p-2 rounded bg-axis-pink-soft border border-axis-magenta text-xs text-axis-burgundy">
          {error}
        </div>
      )}

      {/* R2 still uses the 3-tile proposal grid because Round 2 needs a
          real calendar intersection with every panellist. Round 1 skips
          this grid entirely — R1 is a conversational AI interview, so
          the candidate picks via the Start-now / custom date-time panel
          below instead. */}
      {round === "R2" && (
        <>
          <div
            className="mt-4 grid sm:grid-cols-3 gap-3"
            role="radiogroup"
            aria-label={`${round} interview slots`}
          >
            {slots.map((slot, idx) => {
              const start = new Date(slot.start);
              const end = new Date(slot.end);
              const isSelected = selectedIdx === idx;
              return (
                <button
                  key={idx}
                  role="radio"
                  aria-checked={isSelected}
                  onClick={() => onSelect(idx)}
                  className={`text-left p-3 rounded border-2 transition outline-none focus-visible:ring-2 focus-visible:ring-axis-magenta/50 ${
                    isSelected
                      ? "border-axis-magenta bg-axis-pink-soft shadow-card"
                      : "border-axis-divider hover:border-axis-magenta/60 hover:bg-axis-pink-soft/40"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
                      Slot {idx + 1}
                    </p>
                    {isSelected && (
                      <span
                        className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-axis-magenta text-white text-[10px] leading-none"
                        aria-hidden
                      >
                        ✓
                      </span>
                    )}
                  </div>
                  <p className="text-sm font-semibold text-axis-ink mt-1">
                    {start.toLocaleDateString(undefined, {
                      weekday: "short",
                      day: "numeric",
                      month: "short",
                    })}
                  </p>
                  <p className="text-xs text-axis-ink-soft">
                    {start.toLocaleTimeString(undefined, {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    –{" "}
                    {end.toLocaleTimeString(undefined, {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    IST
                  </p>
                  <p className="mt-2 text-[10px] text-axis-magenta font-semibold">
                    {isSelected ? "Selected" : "Tap to select"}
                  </p>
                </button>
              );
            })}
          </div>

          <p className="mt-3 text-[11px] text-axis-muted">
            Nothing is booked until you confirm in the next step. You can
            re-tap a tile or cancel at any time.
          </p>
        </>
      )}

      {/* ---------- R1-only: Start now / custom date-time picker ----------
          Round 1 is an AI-driven virtual interview — there is no human
          panel to intersect with, so the candidate chooses here between
          starting the interview immediately or booking any custom
          30-minute slot. This replaces the proposed-tile grid entirely
          for R1 (R2 still uses tiles above). */}
      {round === "R1" && onPickCustomR1 && (
        <div className="mt-4">
          <p className="text-xs text-axis-muted mb-3">
            Round 1 is a conversational AI interview, so you can start
            right now or pick any date and time that suits you. Your slot
            will be a 30-minute block.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            {/* Start now */}
            <button
              type="button"
              onClick={() => onPickCustomR1("now", null)}
              className="text-left p-3 rounded border-2 border-axis-magenta bg-axis-magenta text-white hover:bg-axis-burgundy transition outline-none focus-visible:ring-2 focus-visible:ring-axis-magenta/50"
            >
              <p className="text-[10px] uppercase tracking-wider font-semibold opacity-80">
                Recommended
              </p>
              <p className="text-sm font-semibold mt-1">Start my interview now ▶</p>
              <p className="text-[11px] opacity-80 mt-1">
                Begin your Round 1 interview immediately — no waiting.
              </p>
            </button>

            {/* Pick a later time */}
            <div className="p-3 rounded border-2 border-axis-divider hover:border-axis-magenta/60 bg-axis-surface transition">
              <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
                Pick a date & time
              </p>
              <label
                htmlFor="r1-custom-dt"
                className="sr-only"
              >
                Round 1 interview date and time
              </label>
              <input
                id="r1-custom-dt"
                type="datetime-local"
                value={laterDate}
                min={(() => {
                  const d = new Date();
                  const pad = (n: number) => n.toString().padStart(2, "0");
                  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
                })()}
                onChange={(e) => setLaterDate(e.target.value)}
                className="mt-2 w-full text-sm bg-white border border-axis-divider rounded px-2 py-1.5 text-axis-ink focus:outline-none focus:border-axis-magenta"
              />
              <p className="text-[11px] text-axis-muted mt-1">
                30-minute slot starting at the time you pick.
              </p>
              <button
                type="button"
                onClick={() => {
                  if (!laterDate) return;
                  // Convert the "datetime-local" (naive local) string
                  // into a real ISO datetime with the user's TZ offset
                  // so the backend books at the correct wall-clock
                  // time. `new Date(laterDate)` parses in local TZ.
                  const iso = new Date(laterDate).toISOString();
                  onPickCustomR1("later", iso);
                }}
                disabled={!laterDate}
                className="mt-3 w-full px-3 py-1.5 text-xs font-semibold rounded border border-axis-magenta text-axis-magenta hover:bg-axis-pink-soft disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Schedule for this time →
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * "Your interview is booked" card — replaces the SlotPickerCard once the
 * Teams meeting actually exists. Shows the real date/time, a Join meeting
 * button (deep-links into Teams), and a Reschedule button that's disabled
 * inside the 4-hour cutoff window the backend enforces.
 */
function BookedInterviewCard({
  round,
  interview,
  onReschedule,
  error,
}: {
  round: "R1" | "R2";
  interview: InterviewRecord | null;
  onReschedule: () => void;
  error: string | null;
}) {
  if (!interview || !interview.meeting_slot) {
    return (
      <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-5 text-sm text-axis-muted">
        Loading interview details…
      </div>
    );
  }

  const start = new Date(interview.meeting_slot.start);
  const end = new Date(interview.meeting_slot.end);
  const now = new Date();
  const hoursToStart = (start.getTime() - now.getTime()) / 3_600_000;
  // Backend hard-cutoff is 4 hours; mirror it in the UI so the button
  // disables itself before the user even tries.
  const RESCHEDULE_CUTOFF_HOURS = 4;
  const canReschedule = hoursToStart > RESCHEDULE_CUTOFF_HOURS;
  const dateLabel = start.toLocaleDateString(undefined, {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
  const t = (d: Date) =>
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const timeLabel = `${t(start)} – ${t(end)} IST`;
  const roundLabel = round === "R1" ? "Round 1" : "Round 2 panel";

  return (
    <div className="mt-4 bg-axis-canvas border-2 border-emerald-500/60 rounded-card p-5">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider bg-emerald-600 text-white font-semibold px-2 py-0.5 rounded">
          Confirmed · on your calendar
        </span>
        <span className="text-[10px] uppercase tracking-wider text-axis-muted">
          {roundLabel} interview
        </span>
      </div>

      <h2 className="text-lg font-semibold text-axis-ink mt-2">
        Your {roundLabel} interview is booked
      </h2>

      <div className="mt-4 grid sm:grid-cols-2 gap-4">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
            When
          </p>
          <p className="text-base font-semibold text-axis-ink mt-0.5">
            {dateLabel}
          </p>
          <p className="text-sm text-axis-ink-soft">{timeLabel}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
            Where
          </p>
          <p className="text-sm text-axis-ink mt-0.5">Microsoft Teams meeting</p>
          {interview.teams_join_url ? (
            <a
              href={interview.teams_join_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block mt-1 text-sm font-semibold text-axis-magenta hover:underline break-all"
            >
              Join the Teams meeting →
            </a>
          ) : (
            <p className="text-xs text-axis-muted mt-1">
              Join link will appear in your Outlook calendar invite.
            </p>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-4 p-2 rounded bg-axis-pink-soft border border-axis-magenta text-xs text-axis-burgundy">
          {error}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-axis-divider pt-4">
        <button
          type="button"
          onClick={onReschedule}
          disabled={!canReschedule}
          className="px-3 py-1.5 text-xs font-semibold rounded border border-axis-magenta text-axis-magenta hover:bg-axis-pink-soft disabled:opacity-40 disabled:cursor-not-allowed"
          title={
            canReschedule
              ? "Cancel this meeting and pick a new slot"
              : `Reschedules are locked within ${RESCHEDULE_CUTOFF_HOURS} hours of the meeting — contact your Business Partner`
          }
        >
          Reschedule
        </button>
        {canReschedule ? (
          <p className="text-[11px] text-axis-muted">
            You can reschedule up to{" "}
            <strong className="text-axis-ink">
              {RESCHEDULE_CUTOFF_HOURS} hours
            </strong>{" "}
            before the meeting starts.
          </p>
        ) : (
          <p className="text-[11px] text-axis-burgundy">
            Inside the {RESCHEDULE_CUTOFF_HOURS}-hour cutoff. To change the
            meeting now, please contact your Business Partner directly.
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * Inline card that fetches the structured AI Interview Agent report after R1
 * and renders it for the candidate (and is the same data the panel reads
 * before R2 — full transparency).
 */
function R1ReportCard({ appId, stage }: { appId: string; stage: FunnelStage }) {
  const [report, setReport] = useState<InterviewReport | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    // The report only exists from R1_DONE onwards.
    const ready =
      stage === "r1_done" ||
      stage === "r2_scheduled" ||
      stage === "offer_negotiation" ||
      stage === "offer";
    if (!ready) {
      setReport(null);
      return;
    }
    let cancelled = false;
    api
      .getR1Report(appId)
      .then((r) => {
        if (!cancelled) setReport(r);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [appId, stage]);

  if (!report) return null;

  return (
    <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
            AI Interview Agent · Round 1 report
          </p>
          <h2 className="text-base font-semibold text-axis-ink mt-1">
            {report.headline}
          </h2>
          <p className="text-xs text-axis-muted mt-1">
            Overall <strong className="text-axis-ink">{report.overall_score.toFixed(0)}/100</strong>
            {" · "}
            Recommendation:{" "}
            <span
              className={`font-semibold ${
                report.recommendation === "advance"
                  ? "text-emerald-700"
                  : report.recommendation === "borderline"
                  ? "text-amber-700"
                  : "text-axis-burgundy"
              }`}
            >
              {report.recommendation}
            </span>
          </p>
        </div>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-[10px] uppercase tracking-wider text-axis-magenta hover:underline whitespace-nowrap"
        >
          {open ? "Hide details" : "Show details"}
        </button>
      </div>

      {open && (
        <div className="mt-4 grid md:grid-cols-2 gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold mb-2">
              Per-skill rubric
            </p>
            <ul className="space-y-1">
              {Object.entries(report.rubric_scores).map(([skill, val]) => (
                <li key={skill} className="text-xs text-axis-ink-soft flex justify-between">
                  <span>{skill}</span>
                  <span
                    className={`font-semibold ${
                      val >= 80 ? "text-emerald-700" : val >= 50 ? "text-amber-700" : "text-axis-burgundy"
                    }`}
                  >
                    {val.toFixed(0)}/100
                  </span>
                </li>
              ))}
            </ul>
            {report.red_flags.length > 0 && (
              <>
                <p className="text-[10px] uppercase tracking-wider text-axis-burgundy font-semibold mt-4 mb-2">
                  Red flags
                </p>
                <ul className="space-y-1 list-disc list-inside text-xs text-axis-ink-soft">
                  {report.red_flags.map((flag, i) => (
                    <li key={i}>{flag}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold mb-2">
              Transcript highlights
            </p>
            <ul className="space-y-3">
              {report.transcript_highlights.map((h, i) => (
                <li key={i} className="text-xs text-axis-ink-soft">
                  <p className="italic border-l-2 border-axis-magenta pl-2">"{h.quote}"</p>
                  <p className="text-axis-muted mt-1">{h.why_it_matters}</p>
                </li>
              ))}
            </ul>
            <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold mt-4 mb-2">
              Recommended probes for R2 panel
            </p>
            <ul className="space-y-1 list-disc list-inside text-xs text-axis-ink-soft">
              {report.recommended_probes.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
