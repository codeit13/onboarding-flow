"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Sticky section nav that sits under the global TopBar on every HR page.
 *
 * Gives HR partners (and anyone playing the HR persona during the demo) a
 * one-click path to every surface in the console — dashboard, the kanban,
 * requisitions, the candidate directory, and the ops/observability page.
 *
 * The "active" link is matched on path prefix so deep pages like
 * /hr/applications/foo light up the Funnel link, /hr/jobs/[id] lights up
 * Requisitions, etc.
 */
const LINKS: { href: string; label: string; matchPrefix?: string }[] = [
  { href: "/hr/dashboard", label: "Dashboard" },
  { href: "/hr", label: "Funnel", matchPrefix: "/hr/applications" },
  { href: "/hr/jobs", label: "Requisitions" },
  { href: "/hr/candidates", label: "Candidates" },
  { href: "/hr/bulk-screening", label: "Bulk Screening" },
  { href: "/hr/admin/panels", label: "Panels" },
  { href: "/ops", label: "Ops console" },
];

export function HRSubNav() {
  const pathname = usePathname() || "";

  const isActive = (link: (typeof LINKS)[number]) => {
    if (link.href === "/hr") {
      // Funnel is active only for /hr exactly OR /hr/applications/*
      return (
        pathname === "/hr" ||
        pathname.startsWith("/hr/applications")
      );
    }
    if (link.matchPrefix && pathname.startsWith(link.matchPrefix)) return true;
    return pathname === link.href || pathname.startsWith(link.href + "/");
  };

  return (
    <nav className="bg-axis-canvas border-b border-axis-divider px-8 relative z-30">
      <ul className="flex gap-1 -mb-px">
        {LINKS.map((l) => {
          const active = isActive(l);
          return (
            <li key={l.href}>
              <Link
                href={l.href}
                className={`inline-block px-4 py-3 text-xs font-semibold uppercase tracking-wider border-b-2 transition ${
                  active
                    ? "border-axis-magenta text-axis-magenta"
                    : "border-transparent text-axis-muted hover:text-axis-ink"
                }`}
              >
                {l.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
