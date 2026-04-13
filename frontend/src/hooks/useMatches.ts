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
      const list = await api.get<PaginatedResponse<Match>>("/matches");
      const activeMatches = list.items.filter((m) => m.status === "active");

      const enriched = await Promise.all(
        activeMatches.map(async (match) => {
          // Fetch full match detail to get userAId/userBId
          let fullMatch = match;
          try {
            if (!match.userAId || !match.userBId) {
              fullMatch = await api.get<Match>(`/matches/${match.matchId}`);
            }
          } catch {
            // use what we have
          }

          const otherId = fullMatch.userAId === myId ? fullMatch.userBId : fullMatch.userAId;
          let otherUser: MatchDetail["otherUser"];
          if (otherId) {
            try {
              const profile = await api.get<UserProfile>(`/profiles/${otherId}`);
              otherUser = { userId: otherId, name: profile.name, avatarUrl: profile.avatarUrl };
            } catch {
              otherUser = { userId: otherId, name: "User" };
            }
          } else {
            otherUser = { userId: "unknown", name: "User" };
          }
          return { ...fullMatch, otherUser } as MatchDetail;
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
