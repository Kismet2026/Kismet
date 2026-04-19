export interface Candidate {
  userId: string;
  displayName: string;
  age: number;
  gender: string;
  location?: [number, number]; // [lat, lng]
  city?: string;
  avatarUrl?: string;
  bio?: string;
  interests?: string[];
  baziScore?: number | null; // them→you: outer amber ring
  reverseBaziScore?: number | null; // you→them: inner cream ring
}

export type SwipeAction = "like" | "pass";

export interface SwipeRequest {
  targetUserId: string;
  action: SwipeAction;
}

export interface SwipeResponse {
  swipeId: string;
  action: SwipeAction;
  targetUserId: string;
  timestamp: string;
  matched?: boolean;
  matchId?: string;
}
