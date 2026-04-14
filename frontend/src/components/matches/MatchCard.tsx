"use client";

import Link from "next/link";
import { formatRelativeTime } from "@/lib/utils";
import type { MatchDetail } from "@/types";

interface MatchCardProps {
  match: MatchDetail;
}

export function MatchCard({ match }: MatchCardProps) {
  const { otherUser, lastMessage, unreadCount } = match;
  const name = otherUser?.name ?? "User";
  const initial = name.charAt(0).toUpperCase();
  const bgColor = `hsl(${name.charCodeAt(0) * 7 % 360}, 25%, 22%)`;

  return (
    <Link
      href={`/chat/${match.matchId}`}
      className="flex items-center gap-3 px-4 py-3 hover:bg-card/60 active:bg-card transition-colors rounded-xl"
    >
      {/* Avatar */}
      <div className="relative flex-shrink-0">
        {otherUser?.avatarUrl ? (
          <img
            src={otherUser.avatarUrl}
            alt={name}
            className="w-14 h-14 rounded-full object-cover border-2 border-border/30"
          />
        ) : (
          <div
            className="w-14 h-14 rounded-full flex items-center justify-center text-xl font-bold text-foreground/60 border-2 border-border/30"
            style={{ background: bgColor }}
          >
            {initial}
          </div>
        )}
        {/* Unread dot */}
        {(unreadCount ?? 0) > 0 && (
          <div className="absolute -top-0.5 -right-0.5 w-5 h-5 rounded-full bg-primary flex items-center justify-center">
            <span className="text-[10px] font-bold text-primary-foreground">{unreadCount}</span>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-foreground truncate">{name}</h3>
          {lastMessage && (
            <span className="text-xs text-muted-foreground flex-shrink-0 ml-2">
              {formatRelativeTime(lastMessage.timestamp)}
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground truncate mt-0.5">
          {lastMessage
            ? lastMessage.content
            : "Say hi! Start the conversation."}
        </p>
      </div>
    </Link>
  );
}
