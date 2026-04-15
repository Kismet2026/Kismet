export interface Candidate {
  userId: string;
  displayName: string;
  age: number;
  gender: string;
  location?: [number, number]; // [lat, lng]
  city?: string;
  avatarUrl?: string;
  bio?: string;
  baziScore?: number | null; // your compatibility score for them (forward)
  reverseBaziScore?: number | null; // their compatibility score for you (reverse)
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
