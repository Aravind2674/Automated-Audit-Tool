"use client";

import { useEffect, useState } from "react";

function relativeTime(iso: string, now: number): string {
  const then = new Date(iso).getTime();
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

/**
 * Ticking "as of {relative time}" label with a small live dot -- the one signal on
 * the page that says "this is a connected system reporting current state", not a
 * report rendered once and left static. Re-renders every second on its own; no
 * network traffic, just re-evaluating the same generatedAt against the clock.
 */
export default function LiveIndicator({ generatedAt, live }: { generatedAt: string; live: boolean }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center gap-xs font-body-sm text-body-sm text-on-surface-variant">
      <span className="relative flex h-2 w-2">
        {live && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? "bg-primary" : "bg-on-surface-variant"}`} />
      </span>
      <span>
        {live ? "Live" : "Last run"} · updated {relativeTime(generatedAt, now)}
      </span>
    </div>
  );
}
