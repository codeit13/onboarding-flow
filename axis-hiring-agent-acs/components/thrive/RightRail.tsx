// Right rail — promo card + Quick Links grid.
export function RightRail() {
  return (
    <aside className="w-[260px] shrink-0 space-y-4">
      {/* Promo card */}
      <div className="rounded-card border border-axis-divider bg-axis-canvas p-4 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-axis-pink-soft to-white pointer-events-none" />
        <div className="relative">
          <p className="text-xs text-axis-ink-soft leading-snug">
            window will close on <strong>12th April, 2026</strong>
          </p>
          <button className="mt-3 px-4 py-1.5 bg-axis-magenta text-white text-xs font-semibold rounded hover:bg-axis-magenta-hover transition">
            Click here
          </button>
        </div>
      </div>

      {/* Quick Links */}
      <div className="rounded-card border border-axis-divider bg-axis-canvas p-4">
        <h4 className="font-semibold text-axis-ink text-sm mb-3">Quick Links</h4>
        <div className="grid grid-cols-2 gap-3">
          <QuickLink label="UP-Catalyst" tint="bg-axis-pink-soft" />
          <QuickLink label="Transfer R..." tint="bg-axis-cream" />
          <QuickLink label="Open Learning Lab" tint="bg-axis-pink-banner/60" />
          <QuickLink label="HRespo..." tint="bg-axis-teal/20" />
        </div>
      </div>
    </aside>
  );
}

function QuickLink({ label, tint }: { label: string; tint: string }) {
  return (
    <button className="flex flex-col items-center gap-1.5 p-2 rounded hover:bg-axis-surface transition">
      <div className={`w-10 h-10 rounded ${tint} flex items-center justify-center text-axis-burgundy`}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M9 9h6v6H9z" />
        </svg>
      </div>
      <span className="text-[10px] text-axis-ink-soft text-center leading-tight">{label}</span>
    </button>
  );
}
