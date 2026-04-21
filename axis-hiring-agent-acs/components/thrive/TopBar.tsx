"use client";

// Top app bar — clean 2-row header:
// Row 1: White bar with Axis logo + search + action buttons
// Row 2: Nav links bar with bottom gradient accent

import Link from "next/link";
import { usePathname } from "next/navigation";

export function TopBar() {
  const pathname = usePathname() || "";

  const isCandidateRoute =
    pathname === "/" ||
    pathname.startsWith("/thrive") ||
    pathname.startsWith("/external");

  return (
    <div className="relative z-40">
      {/* ── Row 1: White bar — logo + search + actions ── */}
      <div className="bg-white border-b border-axis-divider">
        <div className="px-6 flex items-center justify-between h-14">
          {/* Left: Axis Bank logo */}
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 bg-axis-burgundy rounded-sm flex items-center justify-center">
                <div className="w-4 h-4 bg-white rounded-sm rotate-45" />
              </div>
              <span className="font-bold tracking-wider text-sm text-axis-burgundy">AXIS BANK</span>
            </Link>
            {/* Thrive wordmark — portal identity */}
            <div className="flex items-center gap-1 border-l border-axis-divider pl-3 ml-1">
              <span className="font-display italic text-xl leading-none text-axis-burgundy">thrive</span>
              <div className="h-1 w-5 bg-gradient-to-r from-axis-accent-gold via-axis-accent-pink to-axis-burgundy rounded-full self-end mb-0.5" />
            </div>
          </div>

          {/* Center: Search bar */}
          <div className="hidden md:flex flex-1 max-w-md mx-8">
            <div className="relative w-full">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-axis-muted" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                type="text"
                placeholder="What are you looking for today?"
                className="w-full pl-10 pr-4 py-2 text-sm border border-axis-divider rounded-full bg-axis-surface focus:outline-none focus:border-axis-burgundy/40 focus:ring-1 focus:ring-axis-burgundy/20 transition"
              />
            </div>
          </div>

          {/* Right: Action buttons */}
          <div className="flex items-center gap-3">
            <Link
              href="/hr"
              className="hidden lg:inline-block text-[12px] text-axis-burgundy font-semibold hover:underline"
            >
              Support
            </Link>
            <Link
              href="/external/intake"
              className="text-[12px] px-4 py-1.5 border border-axis-burgundy text-axis-burgundy rounded-full font-semibold hover:bg-axis-pink-soft transition-colors"
            >
              Apply Now
            </Link>
            <Link
              href="/thrive"
              className="text-[12px] px-4 py-1.5 bg-axis-burgundy text-white rounded-full font-semibold hover:bg-axis-burgundy-dark transition-colors"
            >
              Login
            </Link>
          </div>
        </div>
      </div>

      {/* Gradient accent line under the header */}
      <div className="h-[3px] bg-gradient-to-r from-axis-accent-gold via-axis-accent-pink to-axis-burgundy" />
    </div>
  );
}

function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className={`whitespace-nowrap transition-colors py-2 border-b-2 ${
        active
          ? "text-axis-burgundy font-semibold border-axis-burgundy"
          : "text-axis-ink-soft hover:text-axis-burgundy border-transparent"
      }`}
    >
      {label}
    </Link>
  );
}
