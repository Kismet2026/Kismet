"use client";

import { useState, useRef } from "react";
import { PaperPlaneRight } from "@phosphor-icons/react";

interface ChatInputProps {
  onSend: (content: string) => void;
}

export function ChatInput({ onSend }: ChatInputProps) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
    inputRef.current?.focus();
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-center gap-2 px-4 py-3 border-t border-border/50 bg-card/50 backdrop-blur-sm"
    >
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Type a message..."
        className="flex-1 bg-background/50 rounded-full px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
      />
      <button
        type="submit"
        disabled={!text.trim()}
        className="w-10 h-10 rounded-full bg-primary flex items-center justify-center text-primary-foreground disabled:opacity-40 active:scale-90 transition-all"
      >
        <PaperPlaneRight size={18} weight="fill" />
      </button>
    </form>
  );
}
