"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import { KismetWebSocket } from "@/lib/ws";
import type { Message, PaginatedResponse } from "@/types";

const MOCK_MESSAGES: Message[] = [
  { messageId: "m1", matchId: "match-1", senderId: "u1", content: "Hey! I saw we have a 92 BaZi score 😊", messageType: "text", timestamp: "2026-04-10T14:00:00Z" },
  { messageId: "m2", matchId: "match-1", senderId: "test-123", content: "That's amazing! I've never seen one that high", messageType: "text", timestamp: "2026-04-10T14:01:00Z" },
  { messageId: "m3", matchId: "match-1", senderId: "u1", content: "Right? The stars really aligned for us ✨", messageType: "text", timestamp: "2026-04-10T14:02:00Z" },
  { messageId: "m4", matchId: "match-1", senderId: "test-123", content: "So what's your story? What brought you to Boston?", messageType: "text", timestamp: "2026-04-10T14:05:00Z" },
  { messageId: "m5", matchId: "match-1", senderId: "u1", content: "I moved here for grad school! Studying astrophysics at MIT. You?", messageType: "text", timestamp: "2026-04-10T14:10:00Z" },
  { messageId: "m6", matchId: "match-1", senderId: "u1", content: "Hey! Our BaZi score is amazing 😊", messageType: "text", timestamp: "2026-04-10T14:30:00Z" },
];

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
      const data = await api.get<PaginatedResponse<Message>>(`/messages/${matchId}?limit=50`);
      setMessages(data.items.sort((a, b) => a.timestamp.localeCompare(b.timestamp)));
      if (data.items.length > 0) {
        lastTimestampRef.current = data.items[data.items.length - 1].timestamp;
      }
    } catch {
      // Mock data for demo
      setMessages(MOCK_MESSAGES.filter((m) => m.matchId === matchId || matchId.startsWith("match")));
      lastTimestampRef.current = MOCK_MESSAGES[MOCK_MESSAGES.length - 1]?.timestamp ?? "";
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
        // Content moderation (fire and forget)
        api.post("/moderate/text", { content, context: "chat" }).catch(() => {});

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

    // HTTP polling fallback (every 5s)
    pollRef.current = setInterval(async () => {
      if (!lastTimestampRef.current) return;
      try {
        const data = await api.get<PaginatedResponse<Message>>(
          `/messages/${matchId}/since/${encodeURIComponent(lastTimestampRef.current)}`
        );
        if (data.items.length > 0) {
          const newMsgs = data.items.filter((m) => m.senderId !== myId);
          if (newMsgs.length > 0) {
            setMessages((prev) => [...prev, ...newMsgs]);
            lastTimestampRef.current = data.items[data.items.length - 1].timestamp;
          }
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
