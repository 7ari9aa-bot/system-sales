import React, { useMemo } from 'react';

/**
 * Live animated background: slow-floating soft orbs + subtle grid.
 * Pure CSS animation, GPU-friendly, respects prefers-reduced-motion.
 */
export default function LiveBackground() {
  const orbs = useMemo(
    () =>
      Array.from({ length: 6 }, (_, i) => ({
        id: i,
        size: 280 + (i % 3) * 160,
        top: `${8 + i * 15}%`,
        left: `${(i * 23) % 95}%`,
        delay: `${i * 2.5}s`,
        dur: `${18 + (i % 4) * 6}s`,
        hue: i % 2 === 0 ? 'var(--accent)' : 'var(--coral, #C4885F)',
      })),
    []
  );

  return (
    <div className="live-bg" aria-hidden="true">
      <div className="live-bg-grid" />
      {orbs.map((o) => (
        <span
          key={o.id}
          className="live-bg-orb"
          style={{
            width: o.size,
            height: o.size,
            top: o.top,
            left: o.left,
            animationDelay: o.delay,
            animationDuration: o.dur,
            background: `radial-gradient(circle at 50% 50%, ${o.hue}33, transparent 70%)`,
          }}
        />
      ))}
    </div>
  );
}