"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import { KismetWebSocket } from "@/lib/ws";
import type { Message, PaginatedResponse } from "@/types";

export function useChat(matchId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const myId = getUserIdFromToken() ?? "test-123";
  const wsRef = useRef<KismetWebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastTimestampRef = useRef<string>("");

  // Fetch initial messages
  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<PaginatedResponse<Message>>(`/messages/match/${matchId}?limit=50`);
      setMessages(data.items.sort((a, b) => a.timestamp.localeCompare(b.timestamp)));
      if (data.items.length > 0) {
        lastTimestampRef.current = data.items[data.items.length - 1].timestamp;
      }
    } catch {
      // Don't wipe messages on fetch failure — keep any optimistic messages
    } finally {
      setLoading(false);
    }
  }, [matchId]);

  // Send message
  const sendMessage = useCallback(
    async (content: string) => {
      const optimistic: Message = {
        messageId: `temp-${Date.now()}`,
        matchId,
        senderId: myId,
        content,
        messageType: "text",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);

      try {
        const saved = await api.post<Message>("/messages", {
          matchId,
          content,
          messageType: "text",
        });
        // Replace optimistic with saved
        setMessages((prev) =>
          prev.map((m) => (m.messageId === optimistic.messageId ? saved : m))
        );
      } catch {
        // Keep optimistic message for demo
      }
    },
    [matchId, myId]
  );

  // WebSocket connection
  useEffect(() => {
    fetchHistory();

    // Try WebSocket
    try {
      const ws = new KismetWebSocket(myId, matchId);
      wsRef.current = ws;
      ws.onMessage((data: unknown) => {
        const msg = data as { type?: string } & Message;
        if (msg.type === "newMessage" && msg.senderId !== myId) {
          setMessages((prev) => [...prev, msg]);
          lastTimestampRef.current = msg.timestamp;
        }
      });
      ws.connect();
    } catch {
      // WS unavailable — fall through to polling
    }

    // HTTP polling fallback (every 5s) — re-fetch all messages and merge
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.get<PaginatedResponse<Message>>(
          `/messages/match/${matchId}?limit=50`
        );
        if (data.items.length > 0) {
          const sorted = data.items.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
          setMessages((prev) => {
            const existingIds = new Set(prev.map((m) => m.messageId));
            const newMsgs = sorted.filter((m) => !existingIds.has(m.messageId));
            if (newMsgs.length === 0) return prev;
            return [...prev, ...newMsgs];
          });
          lastTimestampRef.current = sorted[sorted.length - 1].timestamp;
        }
      } catch {
        // silently fail
      }
    }, 5000);

    return () => {
      wsRef.current?.disconnect();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [matchId, myId, fetchHistory]);

  return { messages, loading, sendMessage, myId };
}
