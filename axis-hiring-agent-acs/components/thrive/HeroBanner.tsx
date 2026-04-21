// Hero banner — pink gradient card with "Welcome to thrive" display text.
// The people photo on the right is a CSS-drawn placeholder so the POC has zero
// external image deps; swap for a real asset in /public when available.
export function HeroBanner() {
  return (
    <section className="relative overflow-hidden rounded-card border border-axis-divider">
      <div className="bg-gradient-to-r from-axis-pink-banner to-axis-pink-banner-end h-40 flex items-center px-10 relative">
        {/* decorative circles */}
        <div className="absolute top-4 left-6 w-3 h-3 rounded-full bg-white/60" />
        <div className="absolute top-10 left-24 w-2 h-2 rounded-full bg-axis-magenta/40" />
        <div className="absolute bottom-6 left-48 w-4 h-4 rounded-full bg-white/50" />
        <div className="absolute top-6 left-72 w-3 h-3 rounded-full bg-axis-burgundy/30" />

        <h1 className="font-display text-5xl text-axis-ink italic z-10">
          Welcome to <span className="font-medium">thrive</span>
        </h1>

        {/* people photo placeholder — silhouette block on the right */}
        <div className="absolute right-0 top-0 bottom-0 w-[340px] flex items-end justify-center gap-1 pr-6">
          <div className="w-16 h-32 bg-axis-burgundy/20 rounded-t-full" />
          <div className="w-20 h-36 bg-axis-burgundy/30 rounded-t-full" />
          <div className="w-16 h-32 bg-axis-burgundy/25 rounded-t-full" />
        </div>
      </div>
    </section>
  );
}
