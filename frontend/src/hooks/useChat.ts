"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import { KismetWebSocket } from "@/lib/ws";
import type { Message, PaginatedResponse } from "@/types";

export function useChat(matchId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const myId = getUserIdFromToken() ?? "";
  const wsRef = useRef<KismetWebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch message history from REST API
  const fetchMessages = useCallback(async () => {
    try {
      const data = await api.get<PaginatedResponse<Message>>(
        `/messages/match/${matchId}?limit=50`
      );
      const sorted = (data.items || []).sort((a, b) =>
        a.timestamp.localeCompare(b.timestamp)
      );
      setMessages((prev) => {
        // Merge: keep optimistic (temp-*) messages not yet confirmed
        const serverIds = new Set(sorted.map((m) => m.messageId));
        const pendingOptimistic = prev.filter(
          (m) => m.messageId.startsWith("temp-") && !serverIds.has(m.messageId)
        );
        return [...sorted, ...pendingOptimistic];
      });
    } catch (err) {
      console.error("[Chat] fetch failed:", err);
    }
  }, [matchId]);

  useEffect(() => {
    // 1. Load history
    fetchMessages().finally(() => setLoading(false));

    // 2. Connect WebSocket for real-time
    const ws = new KismetWebSocket(myId, matchId);
    wsRef.current = ws;

    ws.onMessage((data: unknown) => {
      const msg = data as { type?: string } & Partial<Message>;
      if (msg.type === "newMessage" && msg.messageId) {
        setMessages((prev) => {
          // Deduplicate
          if (prev.some((m) => m.messageId === msg.messageId)) return prev;
          return [...prev, msg as Message];
        });
      }
    });

    ws.connect();

    // 3. Polling fallback every 5s (in case WS drops)
    pollRef.current = setInterval(fetchMessages, 5000);

    return () => {
      ws.disconnect();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [matchId, myId, fetchMessages]);

  // Send message via WebSocket (with REST fallback)
  const sendMessage = useCallback(
    async (content: string) => {
      const tempId = `temp-${Date.now()}`;
      const optimistic: Message = {
        messageId: tempId,
        matchId,
        senderId: myId,
        content,
        messageType: "text",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);

      // Try WebSocket first (D3 architecture: WS → send_message.py → persist + broadcast)
      if (wsRef.current?.isConnected) {
        wsRef.current.send({ action: "sendMessage", content, messageType: "text" });
      } else {
        // Fallback to REST
        try {
          await api.post<Message>("/messages", {
            matchId,
            content,
            messageType: "text",
          });
        } catch {
          // Message will be picked up by next poll if it persisted
        }
      }

      // Next poll will replace temp message with real one
    },
    [matchId, myId]
  );

  return { messages, loading, sendMessage, myId };
}
