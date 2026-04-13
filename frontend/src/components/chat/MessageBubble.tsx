"use client";

import { cn } from "@/lib/utils";
import type { Message } from "@/types";

interface MessageBubbleProps {
  message: Message;
  isMine: boolean;
}

export function MessageBubble({ message, isMine }: MessageBubbleProps) {
  const time = new Date(message.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className={cn("flex", isMine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5",
          isMine
            ? "bg-primary text-primary-foreground rounded-br-sm"
            : "bg-card text-foreground rounded-bl-sm"
        )}
      >
        <p className="text-sm leading-relaxed break-words">{message.content}</p>
        <p
          className={cn(
            "text-[10px] mt-1",
            isMine ? "text-primary-foreground/60" : "text-muted-foreground"
          )}
        >
          {time}
        </p>
      </div>
    </div>
  );
}
