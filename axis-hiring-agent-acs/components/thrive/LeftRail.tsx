// Left rail nav — narrow icon+label column. Home, Open Learning Lab, UP.
// Selected item gets a magenta left border and pink-soft background.
type NavItem = { label: string; icon: React.ReactNode; active?: boolean };

const items: NavItem[] = [
  {
    label: "Home",
    active: true,
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 9.5L12 3l9 6.5V21a1 1 0 0 1-1 1h-5v-7h-6v7H4a1 1 0 0 1-1-1z" />
      </svg>
    ),
  },
  {
    label: "Open Learning Lab",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5z" />
      </svg>
    ),
  },
  {
    label: "UP",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 19V5M5 12l7-7 7 7" />
      </svg>
    ),
  },
];

export function LeftRail() {
  return (
    <aside className="w-[88px] shrink-0 bg-axis-canvas border-r border-axis-divider flex flex-col justify-between py-4">
      <nav className="flex flex-col gap-1">
        {items.map((item) => (
          <button
            key={item.label}
            className={`flex flex-col items-center gap-1 py-3 text-[11px] leading-tight text-center relative transition ${
              item.active
                ? "text-axis-burgundy bg-axis-pink-soft"
                : "text-axis-ink-soft hover:bg-axis-surface"
            }`}
          >
            {item.active && (
              <span className="absolute left-0 top-0 bottom-0 w-[3px] bg-axis-burgundy rounded-r" />
            )}
            <span>{item.icon}</span>
            <span className="px-1">{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Last login footer */}
      <div className="px-2 text-center">
        <div className="w-8 h-8 mx-auto rounded-full bg-axis-pink-soft flex items-center justify-center text-axis-burgundy text-xs mb-1">
          ◆
        </div>
        <p className="text-[9px] text-axis-muted leading-tight">
          Last Login:
          <br />4 April 2026
          <br />
          03:28:34 PM
        </p>
      </div>
    </aside>
  );
}
