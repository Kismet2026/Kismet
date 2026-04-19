"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { Candidate, PaginatedResponse, SwipeResponse } from "@/types";

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
      // Normalize: /recommend returns `score`, /discovery returns `baziScore`
      const normalized = data.items.map((c) => ({
        ...c,
        baziScore: c.baziScore ?? (c as unknown as Record<string, number>).score ?? null,
      }));
      if (normalized.length === 0) {
        setExhausted(true);
      } else {
        setCandidates((prev) => {
          const existingIds = new Set(prev.map((c) => c.userId));
          const newItems = normalized.filter((c) => !existingIds.has(c.userId));
          return [...prev, ...newItems];
        });
      }
    } catch {
      setExhausted(true);
    } finally {
      setLoading(false);
    }
  }, [loading]);

  const swipe = useCallback(
    async (targetUserId: string, action: "like" | "pass") => {
      setCandidates((prev) => prev.filter((c) => c.userId !== targetUserId));
      const result = await api.post<SwipeResponse>("/swipe", { targetUserId, action });
      return result;
    },
    []
  );

  return { candidates, loading, exhausted, fetchCandidates, swipe };
}
