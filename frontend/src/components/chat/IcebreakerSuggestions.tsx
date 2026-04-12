"use client";

import { Sparkle } from "@phosphor-icons/react";
import type { IcebreakerSuggestion } from "@/types";

interface IcebreakerSuggestionsProps {
  icebreakers: IcebreakerSuggestion[];
  onSelect: (text: string) => void;
}

export function IcebreakerSuggestions({ icebreakers, onSelect }: IcebreakerSuggestionsProps) {
  if (icebreakers.length === 0) return null;

  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-1.5 mb-2">
        <Sparkle size={14} className="text-primary" weight="fill" />
        <span className="text-xs text-muted-foreground">Break the ice</span>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
        {icebreakers.map((ice) => (
          <button
            key={ice.id}
            onClick={() => onSelect(ice.text)}
            className="flex-shrink-0 rounded-full bg-card border border-border/50 px-4 py-2 text-xs text-foreground hover:border-primary/50 hover:bg-primary/5 active:scale-95 transition-all max-w-[200px] text-left"
          >
            {ice.text}
          </button>
        ))}
      </div>
    </div>
  );
}
