"use client";

import { useCallback } from "react";
import { AnimatePresence } from "framer-motion";
import { SwipeCard } from "./SwipeCard";
import type { Candidate } from "@/types";

interface SwipeStackProps {
  candidates: Candidate[];
  onSwipe: (targetUserId: string, action: "like" | "pass") => Promise<{ matched?: boolean; matchId?: string }>;
  onMatch: (matchId: string, candidate: Candidate) => void;
  onTap?: (candidate: Candidate) => void;
}

export function SwipeStack({ candidates, onSwipe, onMatch, onTap }: SwipeStackProps) {
  const visibleCards = candidates.slice(0, 2);
  const topCard = visibleCards[0];

  const handleSwipe = useCallback(
    async (action: "like" | "pass") => {
      if (!topCard) return;
      const result = await onSwipe(topCard.userId, action);
      if (result.matched && result.matchId) {
        onMatch(result.matchId, topCard);
      }
    },
    [topCard, onSwipe, onMatch]
  );

  return (
    <div className="flex flex-col items-center w-full">
      <div className="relative w-full" style={{ height: "min(72dvh, 580px)" }}>
        <AnimatePresence>
          {visibleCards.map((candidate, i) => (
            <SwipeCard
              key={candidate.userId}
              candidate={candidate}
              onSwipe={(action) => {
                if (i === 0) handleSwipe(action);
              }}
              onTap={() => {
                if (i === 0 && onTap) onTap(candidate);
              }}
              isTop={i === 0}
            />
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
