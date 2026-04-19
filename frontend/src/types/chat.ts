export interface Message {
  messageId: string;
  matchId: string;
  senderId: string;
  content: string;
  messageType: "text";
  timestamp: string;
  deleted?: boolean;
}

export interface ChatPresence {
  userId: string;
  isOnline: boolean;
  lastSeen?: string;
}

export interface TypingStatus {
  userId: string;
  isTyping: boolean;
}

export interface IcebreakerSuggestion {
  id: string;
  text: string;
}
