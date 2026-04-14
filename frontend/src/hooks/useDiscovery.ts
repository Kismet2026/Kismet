"use client";

import { useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type { Candidate, PaginatedResponse, SwipeResponse } from "@/types";

export function useDiscovery() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [exhausted, setExhausted] = useState(false);
  const fetchedRef = useRef(false);

  const fetchCandidates = useCallback(async () => {
    if (loading || fetchedRef.current) return;
    fetchedRef.current = true;
    setLoading(true);
    try {
      let data: PaginatedResponse<Candidate>;
      try {
        data = await api.get<PaginatedResponse<Candidate>>("/recommend");
      } catch {
        data = await api.get<PaginatedResponse<Candidate>>("/discovery?limit=20");
      }
      // Normalize field names: /recommend uses candidateUserId, /discovery uses userId
      const normalized = data.items.map((c) => ({
        ...c,
        userId: c.userId || (c as unknown as Record<string, string>).candidateUserId,
      }));
      if (normalized.length === 0) {
        setExhausted(true);
      } else {
        setCandidates(normalized);
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
