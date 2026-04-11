"use client";

import { EmptyState } from "@/components/shared/EmptyState";
import { Heart } from "@phosphor-icons/react";

export default function MatchesPage() {
  return (
    <EmptyState
      icon={Heart}
      title="Matches"
      description="Your matches will appear here"
      className="flex-1"
    />
  );
}
