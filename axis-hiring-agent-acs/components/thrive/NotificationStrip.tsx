// Slim cream strip with megaphone icon — "More opportunities are loading..."
export function NotificationStrip() {
  return (
    <div className="bg-axis-cream border border-axis-cream-border rounded-card flex items-center gap-3 px-4 py-2.5 mt-4">
      <div className="w-8 h-8 rounded-full bg-white flex items-center justify-center shrink-0">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#E8B923" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 11l18-5v12L3 13v-2z" />
          <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
        </svg>
      </div>
      <p className="text-sm text-axis-ink-soft">
        More opportunities are loading...Stay tuned.
      </p>
    </div>
  );
}
