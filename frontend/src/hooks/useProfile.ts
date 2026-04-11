"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import type { UserProfile } from "@/types";

export function useProfile(userId?: string) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const targetId = userId ?? getUserIdFromToken();

  const fetchProfile = useCallback(async () => {
    if (!targetId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<UserProfile>(`/profiles/${targetId}`);
      setProfile(data);
    } catch {
      setProfile(null);
      setError("Failed to load profile");
    } finally {
      setLoading(false);
    }
  }, [targetId]);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  const createProfile = useCallback(
    async (data: Omit<UserProfile, "userId" | "createdAt" | "updatedAt" | "avatarUrl">) => {
      const result = await api.post<UserProfile>("/profiles", data);
      setProfile(result);
      return result;
    },
    []
  );

  const updateProfile = useCallback(
    async (data: Partial<UserProfile>) => {
      if (!targetId) throw new Error("No user ID");
      const result = await api.put<UserProfile>(`/profiles/${targetId}`, data);
      setProfile(result);
      return result;
    },
    [targetId]
  );

  return { profile, loading, error, fetchProfile, createProfile, updateProfile };
}
