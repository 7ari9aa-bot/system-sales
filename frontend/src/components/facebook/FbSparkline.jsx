import React from "react";
import { FB } from "@/components/facebook/fbTheme";
import { chartPath } from "@/lib/facebookApi";

const W = 300;
const H = 64;
const PAD = 4;

/** A small daily chart under an insights number. Each day is a point you can hover or focus to read
 *  its date and value; the whole chart has a plain-text description for screen readers. */
export default function FbSparkline({ series, label, lang = "ar" }) {
  if (!series?.length) return null;
  const ar = lang === "ar";
  const values = series.map((p) => p.value);
  const { line, area } = chartPath(series, W, H - PAD * 2);
  const summary = ar
    ? `${label}: ${series.length} ${series.length === 1 ? "يوم" : "أيام"}، من ${values[0]} إلى ${values.at(-1)}، الأعلى ${Math.max(...values)}`
    : `${label}: ${series.length} ${series.length === 1 ? "day" : "days"}, from ${values[0]} to ${values.at(-1)}, highest ${Math.max(...values)}`;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const cy = (v) => PAD + (max === min ? (H - PAD * 2) / 2 : (H - PAD * 2) - ((v - min) / (max - min)) * (H - PAD * 2));
  const cx = (i) => (series.length === 1 ? W / 2 : (i / (series.length - 1)) * W);
  return (
    <svg role="img" aria-label={summary} viewBox={`0 0 ${W} ${H}`} className="mt-2 h-16 w-full overflow-visible" preserveAspectRatio="none" style={{ direction: "ltr" }}>
      <g transform={`translate(0 ${PAD})`}>
        <path d={area} fill={FB.blue} fillOpacity="0.1" />
        <path d={line} fill="none" stroke={FB.blue} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </g>
      {series.map((p, i) => (
        <circle key={p.day} cx={cx(i)} cy={cy(p.value)} r="5" fill={FB.blue} fillOpacity="0" tabIndex={0} className="hover:fill-opacity-100 focus:fill-opacity-100 focus:outline-none">
          <title>{`${p.day}: ${p.value}`}</title>
        </circle>
      ))}
    </svg>
  );
}
