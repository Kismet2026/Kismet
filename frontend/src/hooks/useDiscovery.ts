"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { Candidate, PaginatedResponse, SwipeResponse } from "@/types";

const MOCK_CANDIDATES: Candidate[] = [
  { userId: "demo-1", displayName: "Sophia", age: 24, gender: "female", city: "Boston", bio: "Love hiking, coffee, and stargazing. Let the stars decide our fate.", baziScore: 92 },
  { userId: "demo-2", displayName: "Lina", age: 26, gender: "female", city: "New York", bio: "Photographer & bookworm. Looking for someone to explore the city with.", baziScore: 78 },
  { userId: "demo-3", displayName: "Maya", age: 23, gender: "female", city: "San Francisco", bio: "Yoga instructor by day, foodie by night. Good vibes only.", baziScore: 65 },
  { userId: "demo-4", displayName: "Aiko", age: 25, gender: "female", city: "Seattle", bio: "Software engineer who loves cats, ramen, and rainy days.", baziScore: 85 },
  { userId: "demo-5", displayName: "Chloe", age: 27, gender: "female", city: "Chicago", bio: "Jazz musician. Looking for someone who appreciates the art of improvisation.", baziScore: 71 },
];

export function useDiscovery() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [exhausted, setExhausted] = useState(false);

  const fetchCandidates = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    try {
      // Try /recommend first (BaZi-ranked), fallback to /discovery
      let data: PaginatedResponse<Candidate>;
      try {
        data = await api.get<PaginatedResponse<Candidate>>("/recommend");
      } catch {
        data = await api.get<PaginatedResponse<Candidate>>("/discovery?limit=20");
      }
      if (data.items.length === 0) {
        setExhausted(true);
      } else {
        setCandidates((prev) => [...prev, ...data.items]);
      }
    } catch {
      // API unavailable — use mock data for demo
      if (candidates.length === 0) {
        setCandidates(MOCK_CANDIDATES);
      }
    } finally {
      setLoading(false);
    }
  }, [loading, candidates.length]);

  const swipe = useCallback(
    async (targetUserId: string, action: "like" | "pass") => {
      // Remove from local list immediately
      setCandidates((prev) => prev.filter((c) => c.userId !== targetUserId));

      // Try posting to backend, return mock response if unavailable
      try {
        return await api.post<SwipeResponse>("/swipe", { targetUserId, action });
      } catch {
        // Mock response for demo
        const matched = action === "like" && Math.random() > 0.6;
        return {
          swipeId: `mock-${Date.now()}`,
          action,
          targetUserId,
          timestamp: new Date().toISOString(),
          matched,
          matchId: matched ? `match-${Date.now()}` : undefined,
        } as SwipeResponse;
      }
    },
    []
  );

  return { candidates, loading, exhausted, fetchCandidates, swipe };
}
