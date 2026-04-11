"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import { useChat } from "@/hooks/useChat";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { ChatInput } from "@/components/chat/ChatInput";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ArrowLeft } from "@phosphor-icons/react";

export default function ChatPage({
  params,
}: {
  params: Promise<{ matchId: string }>;
}) {
  const { matchId } = use(params);
  const router = useRouter();
  const { messages, loading, sendMessage, myId } = useChat(matchId);

  return (
    <div className="flex flex-col h-dvh">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border/50 bg-card/50 backdrop-blur-sm">
        <button
          onClick={() => router.push("/matches")}
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft size={24} />
        </button>
        <div className="flex-1">
          <h2 className="font-semibold text-foreground">Chat</h2>
        </div>
      </div>

      {/* Messages */}
      {loading ? (
        <LoadingSpinner size={32} className="flex-1" />
      ) : (
        <ChatWindow messages={messages} myId={myId} />
      )}

      {/* Input */}
      <ChatInput onSend={sendMessage} />
    </div>
  );
}
