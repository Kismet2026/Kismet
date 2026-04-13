import { jwtDecode } from "jwt-decode";
import type { AuthTokens } from "@/types";

const STORAGE_KEYS = {
  accessToken: "kismet_access_token",
  refreshToken: "kismet_refresh_token",
  idToken: "kismet_id_token",
  expiresAt: "kismet_expires_at",
} as const;

export function saveTokens(tokens: AuthTokens): void {
  const expiresAt = Date.now() + tokens.expiresIn * 1000;
  localStorage.setItem(STORAGE_KEYS.accessToken, tokens.accessToken);
  localStorage.setItem(STORAGE_KEYS.refreshToken, tokens.refreshToken);
  localStorage.setItem(STORAGE_KEYS.idToken, tokens.idToken);
  localStorage.setItem(STORAGE_KEYS.expiresAt, String(expiresAt));
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  // Cognito User Pool Authorizer requires idToken, not accessToken
  const token = localStorage.getItem(STORAGE_KEYS.idToken);
  const expiresAt = localStorage.getItem(STORAGE_KEYS.expiresAt);
  if (!token || !expiresAt) return null;
  // 30s buffer before expiry
  if (Date.now() >= Number(expiresAt) - 30_000) return null;
  return token;
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(STORAGE_KEYS.refreshToken);
}

export function getUserIdFromToken(): string | null {
  if (typeof window === "undefined") return null;
  const idToken = localStorage.getItem(STORAGE_KEYS.idToken);
  if (!idToken) return null;
  try {
    const decoded = jwtDecode<{ sub: string }>(idToken);
    return decoded.sub;
  } catch {
    return null;
  }
}

export function clearTokens(): void {
  Object.values(STORAGE_KEYS).forEach((key) => localStorage.removeItem(key));
}

export function isAuthenticated(): boolean {
  return getAccessToken() !== null;
}
