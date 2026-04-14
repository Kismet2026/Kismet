"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { IcebreakerSuggestion } from "@/types";

const MOCK_ICEBREAKERS: IcebreakerSuggestion[] = [
  { id: "ice-1", text: "What's the most adventurous thing you've ever done?" },
  { id: "ice-2", text: "If you could travel anywhere tomorrow, where would you go?" },
  { id: "ice-3", text: "What's your go-to comfort food?" },
  { id: "ice-4", text: "Do you believe in fate? 🌙" },
];

export function useIcebreakers(matchId: string) {
  const [icebreakers, setIcebreakers] = useState<IcebreakerSuggestion[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchIcebreakers = useCallback(async () => {
    setLoading(true);
    try {
      // Try cached first
      const cached = await api.get<{ suggestions: IcebreakerSuggestion[] }>(`/icebreaker/${matchId}`);
      if (cached.suggestions?.length > 0) {
        setIcebreakers(cached.suggestions);
        return;
      }
    } catch {
      // No cached — generate new
    }

    try {
      const generated = await api.post<{ suggestions: IcebreakerSuggestion[] }>("/icebreaker/generate", { matchId });
      setIcebreakers(generated.suggestions ?? []);
    } catch {
      setIcebreakers(MOCK_ICEBREAKERS);
    } finally {
      setLoading(false);
    }
  }, [matchId]);

  useEffect(() => {
    fetchIcebreakers();
  }, [fetchIcebreakers]);

  return { icebreakers, loading };
}
