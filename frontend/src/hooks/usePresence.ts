"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type { ChatPresence, TypingStatus } from "@/types";

/** Send heartbeat every 30s to indicate online status */
export function useHeartbeat() {
  useEffect(() => {
    const sendHeartbeat = () => {
      api.post("/presence/heartbeat").catch(() => {});
    };
    sendHeartbeat();
    const interval = setInterval(sendHeartbeat, 30000);
    return () => clearInterval(interval);
  }, []);
}

/** Check if a user is online */
export function useOnlineStatus(userId: string | undefined) {
  const [isOnline, setIsOnline] = useState(false);

  useEffect(() => {
    if (!userId) return;

    const check = async () => {
      try {
        const data = await api.get<ChatPresence>(`/presence/user/${userId}`);
        setIsOnline(data.isOnline);
      } catch {
        setIsOnline(false);
      }
    };

    check();
    const interval = setInterval(check, 15000);
    return () => clearInterval(interval);
  }, [userId]);

  return isOnline;
}

/** Typing indicator — send signals and poll for other person's typing */
export function useTyping(matchId: string, myId: string) {
  const [otherTyping, setOtherTyping] = useState(false);
  const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSentRef = useRef(0);

  // Poll for other person's typing status
  useEffect(() => {
    const check = async () => {
      try {
        const data = await api.get<TypingStatus>(`/presence/${matchId}/typing`);
        setOtherTyping(data.isTyping && data.userId !== myId);
      } catch {
        setOtherTyping(false);
      }
    };

    const interval = setInterval(check, 2000);
    return () => clearInterval(interval);
  }, [matchId, myId]);

  // Send typing signal (debounced — max once per 2s)
  const sendTyping = useCallback(() => {
    const now = Date.now();
    if (now - lastSentRef.current < 2000) return;
    lastSentRef.current = now;

    api.post(`/presence/${matchId}/typing`).catch(() => {});

    // Auto-clear after 3s of no typing
    if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current);
    typingTimeoutRef.current = setTimeout(() => {
      lastSentRef.current = 0;
    }, 3000);
  }, [matchId]);

  return { otherTyping, sendTyping };
}
