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

  const fetchMessages = useCallback(async () => {
    try {
      const data = await api.get<PaginatedResponse<Message>>(
        `/messages/match/${matchId}?limit=50`
      );
      const sorted = (data.items || []).sort((a, b) =>
        a.timestamp.localeCompare(b.timestamp)
      );
      setMessages((prev) => {
        const serverIds = new Set(sorted.map((m) => m.messageId));
        const pendingOptimistic = prev.filter(
          (m) => m.messageId.startsWith("temp-") && !serverIds.has(m.messageId)
        );
        return [...sorted, ...pendingOptimistic];
      });
    } catch {
      // Keep existing messages on error
    }
  }, [matchId]);

  useEffect(() => {
    fetchMessages().finally(() => setLoading(false));

    const ws = new KismetWebSocket(myId, matchId);
    wsRef.current = ws;

    ws.onMessage((data: unknown) => {
      const msg = data as { type?: string } & Partial<Message>;
      // Only add messages from OTHER users — our own messages are already shown optimistically
      if (msg.type === "newMessage" && msg.messageId && msg.senderId !== myId) {
        setMessages((prev) => {
          if (prev.some((m) => m.messageId === msg.messageId)) return prev;
          return [...prev, msg as Message];
        });
      }
    });

    ws.connect();

    pollRef.current = setInterval(fetchMessages, 5000);

    return () => {
      ws.disconnect();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [matchId, myId, fetchMessages]);

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

      if (wsRef.current?.isConnected) {
        wsRef.current.send({ action: "sendMessage", content, messageType: "text" });
      } else {
        try {
          await api.post<Message>("/messages", { matchId, content, messageType: "text" });
        } catch {
          // Next poll will pick up if persisted
        }
      }
    },
    [matchId, myId]
  );

  return { messages, loading, sendMessage, myId };
}
