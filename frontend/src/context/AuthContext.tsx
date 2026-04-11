"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import {
  saveTokens,
  clearTokens,
  getAccessToken,
  getUserIdFromToken,
} from "@/lib/auth";
import { api } from "@/lib/api";
import type { AuthTokens } from "@/types";

interface AuthState {
  userId: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, birthDate: string, birthTime?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    userId: null,
    isAuthenticated: false,
    isLoading: true,
  });

  // Hydrate from localStorage on mount
  useEffect(() => {
    const token = getAccessToken();
    const userId = getUserIdFromToken();
    setState({
      userId: token ? userId : null,
      isAuthenticated: !!token,
      isLoading: false,
    });
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api.post<AuthTokens>("/auth/login", { email, password });
    saveTokens(tokens);
    const userId = getUserIdFromToken();
    setState({ userId, isAuthenticated: true, isLoading: false });
  }, []);

  const signup = useCallback(
    async (email: string, password: string, birthDate: string, birthTime?: string) => {
      const body: Record<string, string> = { email, password, birthDate };
      if (birthTime) body.birthTime = birthTime;
      await api.post("/auth/signup", body);
      // Don't auto-login — user must verify email first
    },
    []
  );

  const logout = useCallback(() => {
    const refreshToken = typeof window !== "undefined" ? localStorage.getItem("kismet_refresh_token") : null;
    if (refreshToken) {
      // Fire and forget
      api.post("/auth/logout", { refreshToken }).catch(() => {});
    }
    clearTokens();
    setState({ userId: null, isAuthenticated: false, isLoading: false });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
