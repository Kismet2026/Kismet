"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import type { Match, MatchDetail, UserProfile, Message, PaginatedResponse } from "@/types";

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

          // Fetch other user's profile
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

          // Fetch last message for this match
          let lastMessage: MatchDetail["lastMessage"];
          try {
            const msgs = await api.get<PaginatedResponse<Message>>(
              `/messages/match/${match.matchId}?limit=1`
            );
            if (msgs.items.length > 0) {
              const m = msgs.items[0];
              lastMessage = {
                content: m.content,
                timestamp: m.timestamp,
                senderId: m.senderId,
              };
            }
          } catch {
            // no messages yet
          }

          return { ...fullMatch, otherUser, lastMessage } as MatchDetail;
        })
      );

      // Sort: matches with recent messages first
      enriched.sort((a, b) => {
        const ta = a.lastMessage?.timestamp ?? a.matchedAt ?? "";
        const tb = b.lastMessage?.timestamp ?? b.matchedAt ?? "";
        return tb.localeCompare(ta);
      });

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
