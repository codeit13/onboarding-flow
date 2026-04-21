import Link from "next/link";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";

export default function HomePage() {
  return (
    <>
      <TopBar />
      <main className="min-h-screen bg-axis-surface">
        {/* Hero — clean white background with burgundy text, matching axis.bank.in's airy feel */}
        <section className="relative overflow-hidden bg-white">
          {/* Subtle decorative gradient overlay */}
          <div
            aria-hidden
            className="absolute inset-0 bg-gradient-to-br from-axis-pink-soft via-white to-white"
          />
          <div className="relative max-w-6xl mx-auto px-6 pt-20 pb-24">
            <div className="h-1 w-20 bg-gradient-to-r from-axis-burgundy to-axis-accent-pink rounded mb-6" />
            <p className="text-xs uppercase tracking-[0.25em] text-axis-burgundy font-semibold mb-3">
              Axis Bank · Hiring
            </p>
            <h1 className="text-5xl md:text-6xl font-display leading-tight mb-5 text-axis-ink">
              The Axis Hiring Experience
            </h1>
            <p className="text-lg text-axis-muted max-w-2xl mb-10 leading-relaxed">
              One seamless hiring journey for every role at Axis — from your
              first click to a signed offer. Built for speed, fairness, and
              a human touch at every step.
            </p>
            <div className="flex flex-wrap gap-4">
              <Link
                href="/thrive"
                className="inline-flex items-center gap-2 bg-axis-burgundy text-white text-sm font-semibold px-6 py-3 rounded-btn shadow-card hover:bg-axis-burgundy-dark transition"
              >
                I&apos;m an Axis employee →
              </Link>
              <Link
                href="/external/intake"
                className="inline-flex items-center gap-2 bg-white border-2 border-axis-burgundy text-axis-burgundy text-sm font-semibold px-6 py-3 rounded-btn hover:bg-axis-pink-soft transition"
              >
                I&apos;m applying from outside Axis →
              </Link>
            </div>
          </div>
        </section>

        {/* Persona cards */}
        <section className="max-w-6xl mx-auto px-6 pt-14 pb-20">
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
            <PersonaCard
              href="/thrive"
              icon="👤"
              subtitle="Employee · Thrive"
              title="Grow with Axis"
              body="Discover open roles matched to your profile, track your application, and receive interview details — all in one place."
              cta="Open Thrive"
            />
            <PersonaCard
              href="/hr"
              icon="🗂️"
              subtitle="Business Partner"
              title="Run the funnel"
              body="See every candidate across every stage, customise checklists per role, and keep hiring moving without chasing updates."
              cta="Open Business Partner console"
            />
            <PersonaCard
              href="/panel"
              icon="🎯"
              subtitle="Interview Panel"
              title="Decide together"
              body="Review the Round 1 summary, cast your Round 2 vote, and see where your peers stand — all on one screen."
              cta="Open Panel queue"
            />
            <PersonaCard
              href="/external/intake"
              icon="📄"
              subtitle="External Candidate"
              title="Apply to Axis"
              body="Tell us what you're looking for in plain English, upload your resume + latest salary slip, and get jobs ranked two ways — by what you said and by what your resume shows."
              cta="Apply now"
              accent
            />
          </div>
        </section>

        {/* How it works */}
        <section className="bg-axis-canvas border-t border-axis-divider">
          <div className="max-w-6xl mx-auto px-6 py-14">
            <div className="h-1 w-16 bg-axis-burgundy rounded mb-4" />
            <h2 className="text-2xl md:text-3xl font-display text-axis-ink mb-2">
              How hiring at Axis works
            </h2>
            <p className="text-axis-muted max-w-2xl mb-10">
              From application to offer, Axis handles the busywork so
              candidates, Business Partners, and panellists can focus on the human decisions
              that matter.
            </p>

            <ol className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
              <Step
                n={1}
                title="Apply"
                body="Employees browse roles in Thrive; external candidates upload a resume. Every profile is scored against the JD in seconds."
              />
              <Step
                n={2}
                title="Schedule Round 1"
                body="Axis intersects calendars, proposes interview slots over email, and books the Teams meeting the moment you pick one."
              />
              <Step
                n={3}
                title="Interview & report"
                body="Round 1 runs on Teams. The conversation is captured, scored against a JD rubric, and a structured report is written for the panel."
              />
              <Step
                n={4}
                title="Panel decision & offer"
                body="The Round 2 panel reviews the Round 1 report, votes, and the outcome is rolled forward — all the way to the offer email."
              />
            </ol>
          </div>
        </section>

        <Footer />
      </main>
    </>
  );
}

function PersonaCard({
  href,
  icon,
  title,
  subtitle,
  body,
  cta,
  accent,
}: {
  href: string;
  icon: string;
  title: string;
  subtitle: string;
  body: string;
  cta: string;
  accent?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`group block bg-white border rounded-card shadow-card p-6 transition-all duration-200 hover:-translate-y-1 hover:shadow-card-hover ${
        accent
          ? "border-axis-burgundy border-2"
          : "border-axis-divider hover:border-axis-burgundy"
      }`}
    >
      <div
        className={`w-12 h-12 rounded-xl flex items-center justify-center text-xl mb-4 ${
          accent ? "bg-axis-burgundy/10" : "bg-axis-pink-soft"
        }`}
        aria-hidden
      >
        {icon}
      </div>
      <p className="text-[10px] uppercase tracking-widest text-axis-burgundy font-bold mb-1">
        {subtitle}
      </p>
      <h2 className="text-lg font-display text-axis-ink mb-2">{title}</h2>
      <p className="text-sm text-axis-muted mb-5 min-h-[5rem] leading-relaxed">
        {body}
      </p>
      <span className="text-sm font-semibold text-axis-burgundy group-hover:underline">
        {cta} →
      </span>
    </Link>
  );
}

function Step({
  n,
  title,
  body,
}: {
  n: number;
  title: string;
  body: string;
}) {
  return (
    <li className="relative bg-white border border-axis-divider rounded-card p-6">
      <div className="absolute -top-3.5 left-5 bg-axis-burgundy text-white text-xs font-bold w-8 h-8 rounded-full flex items-center justify-center shadow-card">
        {n}
      </div>
      <h3 className="mt-4 text-base font-display text-axis-ink mb-2">
        {title}
      </h3>
      <p className="text-[13px] text-axis-muted leading-relaxed">{body}</p>
    </li>
  );
}
