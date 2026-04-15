"use client";

import { cn } from "@/lib/utils";

interface YinYangScoreProps {
  forward: number | null | undefined; // your score for them
  reverse: number | null | undefined; // their score for you
  size?: "sm" | "md" | "lg";
  showLabels?: boolean;
}

/**
 * Dual-ring BaZi compatibility badge in yin-yang style.
 * Outer arc = forward (your side, amber/gold)
 * Inner arc = reverse (their side, silver/cream)
 * Center = average score with ✦ accent
 */
export function YinYangScore({ forward, reverse, size = "md", showLabels = false }: YinYangScoreProps) {
  if (forward == null && reverse == null) return null;

  // pad = half stroke so arcs never clip the container edge
  const dimensions = {
    sm: { box: 48, outer: 19, inner: 12, stroke: 3, pad: 2, fontCenter: "text-[10px]" },
    md: { box: 64, outer: 25, inner: 16, stroke: 4, pad: 3, fontCenter: "text-sm" },
    lg: { box: 88, outer: 35, inner: 24, stroke: 5, pad: 4, fontCenter: "text-lg" },
  }[size];

  const { box, outer, inner, stroke, pad, fontCenter } = dimensions;
  const center = box / 2;

  const outerCirc = 2 * Math.PI * outer;
  const innerCirc = 2 * Math.PI * inner;

  const fwdPct = forward != null ? Math.min(100, Math.max(0, forward)) / 100 : 0;
  const revPct = reverse != null ? Math.min(100, Math.max(0, reverse)) / 100 : 0;

  const avg =
    forward != null && reverse != null
      ? Math.round((forward + reverse) / 2)
      : forward ?? reverse ?? 0;

  return (
    <div className="inline-flex flex-col items-center gap-1">
      <div
        className="relative"
        style={{ width: box + pad * 2, height: box + pad * 2 }}
      >
        {/* Glow background */}
        <div
          className="absolute inset-0 rounded-full blur-xl opacity-50"
          style={{
            background:
              avg >= 90
                ? "radial-gradient(circle, rgba(212,160,86,0.7), transparent 65%)"
                : avg >= 70
                  ? "radial-gradient(circle, rgba(212,160,86,0.4), transparent 65%)"
                  : "radial-gradient(circle, rgba(167,130,149,0.3), transparent 65%)",
          }}
        />

        <svg
          width={box + pad * 2}
          height={box + pad * 2}
          viewBox={`${-pad} ${-pad} ${box + pad * 2} ${box + pad * 2}`}
          className="relative -rotate-90"
        >
          {/* Outer track */}
          <circle
            cx={center}
            cy={center}
            r={outer}
            fill="none"
            stroke="rgba(239,225,209,0.12)"
            strokeWidth={stroke}
          />
          {/* Outer arc = forward (amber gold) */}
          {forward != null && (
            <circle
              cx={center}
              cy={center}
              r={outer}
              fill="none"
              stroke="url(#fwdGradient)"
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={`${outerCirc * fwdPct} ${outerCirc}`}
            />
          )}

          {/* Inner track */}
          <circle
            cx={center}
            cy={center}
            r={inner}
            fill="none"
            stroke="rgba(239,225,209,0.1)"
            strokeWidth={stroke}
          />
          {/* Inner arc = reverse (cream silver) */}
          {reverse != null && (
            <circle
              cx={center}
              cy={center}
              r={inner}
              fill="none"
              stroke="url(#revGradient)"
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={`${innerCirc * revPct} ${innerCirc}`}
            />
          )}

          <defs>
            <linearGradient id="fwdGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#F5C878" />
              <stop offset="100%" stopColor="#D4A056" />
            </linearGradient>
            <linearGradient id="revGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#EFE1D1" />
              <stop offset="100%" stopColor="#A78295" />
            </linearGradient>
          </defs>
        </svg>

        {/* Center content */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("font-bold text-foreground leading-none", fontCenter)}>
            {avg}
          </span>
          {size === "lg" && (
            <span className="text-[7px] text-foreground/50 uppercase tracking-widest mt-0.5">
              ✦ 合 ✦
            </span>
          )}
        </div>
      </div>

      {showLabels && (
        <div className="flex gap-3 text-[9px] uppercase tracking-wide">
          {forward != null && (
            <span className="text-[#D4A056]">→ {forward}</span>
          )}
          {reverse != null && (
            <span className="text-[#EFE1D1]/80">← {reverse}</span>
          )}
        </div>
      )}
    </div>
  );
}
