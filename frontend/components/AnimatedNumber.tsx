"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Tweens between numeric values instead of silently swapping the text node --
 * a compliance % or findings count that CHANGES should visibly move, so a viewer
 * watching the dashboard during/after a scan can see it update rather than having
 * to notice a static number is now different. Respects prefers-reduced-motion by
 * jumping straight to the target instead of animating.
 */
export default function AnimatedNumber({
  value, decimals = 0, suffix = "", duration = 600,
}: { value: number | null; decimals?: number; suffix?: string; duration?: number }) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (value === null) { setDisplay(null); return; }
    const from = fromRef.current ?? value;
    const to = value;
    if (from === to) { setDisplay(to); return; }

    const reduceMotion = typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) { setDisplay(to); fromRef.current = to; return; }

    const start = performance.now();
    if (rafRef.current) cancelAnimationFrame(rafRef.current);

    function tick(now: number) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setDisplay(from + (to - from) * eased);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  if (display === null) return <>—</>;
  return <>{display.toFixed(decimals)}{suffix}</>;
}
