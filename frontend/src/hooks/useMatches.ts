"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import type { Match, MatchDetail, UserProfile, PaginatedResponse } from "@/types";

const MOCK_MATCHES: MatchDetail[] = [
  {
    matchId: "match-1", userAId: "test-123", userBId: "u1", status: "active", matchedAt: "2026-04-09T10:00:00Z",
    otherUser: { userId: "u1", name: "Sophia", avatarUrl: undefined },
    lastMessage: { content: "Hey! Our BaZi score is amazing 😊", timestamp: "2026-04-10T14:30:00Z", senderId: "u1" },
    unreadCount: 2,
  },
  {
    matchId: "match-2", userAId: "test-123", userBId: "u2", status: "active", matchedAt: "2026-04-08T18:00:00Z",
    otherUser: { userId: "u2", name: "Lina", avatarUrl: undefined },
    lastMessage: { content: "Would love to grab coffee sometime!", timestamp: "2026-04-09T20:15:00Z", senderId: "test-123" },
    unreadCount: 0,
  },
  {
    matchId: "match-3", userAId: "u3", userBId: "test-123", status: "active", matchedAt: "2026-04-07T12:00:00Z",
    otherUser: { userId: "u3", name: "Maya", avatarUrl: undefined },
    lastMessage: undefined,
    unreadCount: 0,
  },
];

export function useMatches() {
  const [matches, setMatches] = useState<MatchDetail[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchMatches = useCallback(async () => {
    setLoading(true);
    const myId = getUserIdFromToken();
    try {
      const data = await api.get<PaginatedResponse<Match>>("/matches");
      // Enrich each match with other user's profile
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
      // API unavailable — use mock data for demo
      setMatches(MOCK_MATCHES);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMatches();
  }, [fetchMatches]);

  return { matches, loading, fetchMatches };
}
