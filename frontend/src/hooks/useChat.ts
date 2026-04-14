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

  // Single source of truth: always fetch from server
  const fetchMessages = useCallback(async () => {
    try {
      const data = await api.get<PaginatedResponse<Message>>(
        `/messages/match/${matchId}?limit=50`
      );
      const sorted = (data.items || []).sort((a, b) =>
        a.timestamp.localeCompare(b.timestamp)
      );
      setMessages(sorted);
    } catch {
      // Keep existing messages on error
    }
  }, [matchId]);

  useEffect(() => {
    // 1. Load history
    fetchMessages().finally(() => setLoading(false));

    // 2. WebSocket — only used to trigger immediate poll when new message arrives
    const ws = new KismetWebSocket(myId, matchId);
    wsRef.current = ws;
    ws.onMessage(() => {
      // Any WS event → immediately refresh from server
      fetchMessages();
    });
    ws.connect();

    // 3. Regular polling as backup
    pollRef.current = setInterval(fetchMessages, 5000);

    return () => {
      ws.disconnect();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [matchId, myId, fetchMessages]);

  // Send message
  const sendMessage = useCallback(
    async (content: string) => {
      // Optimistic: add immediately for instant UX
      const tempMsg: Message = {
        messageId: `temp-${Date.now()}`,
        matchId,
        senderId: myId,
        content,
        messageType: "text",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, tempMsg]);

      // Send via WebSocket or REST
      if (wsRef.current?.isConnected) {
        wsRef.current.send({ action: "sendMessage", content, messageType: "text" });
      } else {
        try {
          await api.post<Message>("/messages", { matchId, content, messageType: "text" });
        } catch {
          // poll will pick up
        }
      }

      // After a short delay, fetch from server to replace temp with real message
      setTimeout(fetchMessages, 1000);
    },
    [matchId, myId, fetchMessages]
  );

  return { messages, loading, sendMessage, myId };
}
