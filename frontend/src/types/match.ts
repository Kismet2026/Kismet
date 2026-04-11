export interface Match {
  matchId: string;
  userAId: string;
  userBId: string;
  status: "active" | "unmatched";
  matchedAt: string;
}

export interface MatchDetail extends Match {
  otherUser?: {
    userId: string;
    name: string;
    avatarUrl?: string;
  };
  lastMessage?: {
    content: string;
    timestamp: string;
    senderId: string;
  };
  unreadCount?: number;
}
