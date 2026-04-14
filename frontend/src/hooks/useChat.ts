"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import { KismetWebSocket } from "@/lib/ws";
import type { Message, PaginatedResponse } from "@/types";

export function useChat(matchId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [debugInfo, setDebugInfo] = useState("");
  const myId = getUserIdFromToken() ?? "";
  const wsRef = useRef<KismetWebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchMessages = useCallback(async () => {
    // Debug: check token state
    const token = typeof window !== "undefined" ? localStorage.getItem("kismet_id_token") : null;
    const expiresAt = typeof window !== "undefined" ? localStorage.getItem("kismet_expires_at") : null;
    const tokenOk = token && token !== "undefined" && token !== "null" && token.length > 20;
    const expired = expiresAt ? Date.now() >= Number(expiresAt) - 30000 : true;

    if (!tokenOk) {
      setDebugInfo(`NO TOKEN: len=${token?.length} val=${token?.slice(0, 10)}`);
      return;
    }
    if (expired) {
      setDebugInfo(`TOKEN EXPIRED: expiresAt=${expiresAt} now=${Date.now()}`);
      // Still try — api.ts will attempt refresh
    }

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
      setDebugInfo(`OK: ${sorted.length} msgs | ws:${wsRef.current?.isConnected ? 'Y' : 'N'}`);
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "message" in err
        ? (err as { message: string }).message : String(err);
      const statusCode = err && typeof err === "object" && "statusCode" in err
        ? (err as { statusCode: number }).statusCode : "?";
      setDebugInfo(`ERR(${statusCode}): ${msg}`);
    }
  }, [matchId]);

  useEffect(() => {
    fetchMessages().finally(() => setLoading(false));

    const ws = new KismetWebSocket(myId, matchId);
    wsRef.current = ws;

    ws.onMessage((data: unknown) => {
      const msg = data as { type?: string } & Partial<Message>;
      if (msg.type === "newMessage" && msg.messageId) {
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
        setDebugInfo("Sent via WS");
      } else {
        try {
          await api.post<Message>("/messages", { matchId, content, messageType: "text" });
          setDebugInfo("Sent via REST");
        } catch (err: unknown) {
          const msg = err && typeof err === "object" && "message" in err
            ? (err as { message: string }).message : String(err);
          setDebugInfo(`Send ERR: ${msg}`);
        }
      }
    },
    [matchId, myId]
  );

  return { messages, loading, sendMessage, myId, debugInfo };
}
