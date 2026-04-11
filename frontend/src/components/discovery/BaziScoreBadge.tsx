"use client";

import { cn } from "@/lib/utils";

interface BaziScoreBadgeProps {
  score: number | null | undefined;
  size?: "sm" | "md";
}

export function BaziScoreBadge({ score, size = "md" }: BaziScoreBadgeProps) {
  if (score == null) return null;

  const tier =
    score >= 90 ? "gold" : score >= 70 ? "silver" : "neutral";

  const colors = {
    gold: "from-amber-400 to-yellow-600 text-amber-950 shadow-amber-500/30",
    silver: "from-slate-300 to-slate-400 text-slate-900 shadow-slate-400/30",
    neutral: "from-muted-foreground/40 to-muted-foreground/60 text-foreground shadow-none",
  };

  return (
    <div
      className={cn(
        "inline-flex items-center justify-center rounded-full bg-gradient-to-br font-bold shadow-lg",
        colors[tier],
        size === "sm" ? "w-9 h-9 text-xs" : "w-12 h-12 text-sm"
      )}
    >
      {score}
    </div>
  );
}
