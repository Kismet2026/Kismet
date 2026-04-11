"use client";

import { useMatches } from "@/hooks/useMatches";
import { MatchCard } from "@/components/matches/MatchCard";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { Heart } from "@phosphor-icons/react";

export default function MatchesPage() {
  const { matches, loading } = useMatches();

  if (loading) {
    return <LoadingSpinner size={48} className="flex-1" />;
  }

  if (matches.length === 0) {
    return (
      <EmptyState
        icon={Heart}
        title="No matches yet"
        description="Start swiping to find your destined match"
        className="flex-1"
      />
    );
  }

  return (
    <div className="flex-1 px-2 py-4 max-w-md mx-auto w-full">
      <h1 className="text-2xl font-bold px-2 mb-4">Matches</h1>
      <div className="space-y-1">
        {matches.map((match) => (
          <MatchCard key={match.matchId} match={match} />
        ))}
      </div>
    </div>
  );
}
