"use client";

import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import type { Message } from "@/types";

interface ChatWindowProps {
  messages: Message[];
  myId: string;
}

export function ChatWindow({ messages, myId }: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  // Track if user is near bottom
  function handleScroll() {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    isNearBottomRef.current = scrollHeight - scrollTop - clientHeight < 100;
  }

  // Auto-scroll to bottom on new messages (if user hasn't scrolled up)
  useEffect(() => {
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length]);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto px-4 py-4 space-y-2"
    >
      {messages.map((msg) => (
        <MessageBubble
          key={msg.messageId}
          message={msg}
          isMine={msg.senderId === myId}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
