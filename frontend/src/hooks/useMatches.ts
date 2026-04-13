"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import type { Match, MatchDetail, UserProfile, PaginatedResponse } from "@/types";

export function useMatches() {
  const [matches, setMatches] = useState<MatchDetail[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchMatches = useCallback(async () => {
    setLoading(true);
    const myId = getUserIdFromToken();
    try {
      const data = await api.get<PaginatedResponse<Match>>("/matches");
      const enriched = await Promise.all(
        data.items
          .filter((m) => m.status === "active")
          .map(async (match) => {
            const otherId = match.userAId === myId ? match.userBId : match.userAId;
            let otherUser: MatchDetail["otherUser"];
            try {
              const profile = await api.get<UserProfile>(`/profiles/${otherId}`);
              otherUser = { userId: otherId, name: profile.name, avatarUrl: profile.avatarUrl };
            } catch {
              otherUser = { userId: otherId, name: "User" };
            }
            return { ...match, otherUser } as MatchDetail;
          })
      );
      setMatches(enriched);
    } catch {
      setMatches([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMatches();
  }, [fetchMatches]);

  return { matches, loading, fetchMatches };
}
