export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  idToken: string;
  expiresIn: number;
}

export interface UserProfile {
  userId: string;
  name: string;
  bio?: string;
  gender: "male" | "female" | "non-binary";
  interestedIn: "male" | "female" | "everyone";
  birthDate: string; // YYYY-MM-DD
  birthTime?: string; // HH:mm, optional — BaZi only uses first 3 pillars
  location?: {
    latitude: number;
    longitude: number;
  };
  city?: string;
  interests: string[];
  avatarUrl?: string;
  createdAt: string;
  updatedAt?: string;
}

export interface Photo {
  photoId: string;
  url: string;
  isPrimary: boolean;
  uploadedAt: string;
}

export interface PhotoUploadResponse {
  photoId: string;
  uploadUrl: string;
  expiresIn: number;
}
