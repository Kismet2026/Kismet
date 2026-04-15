"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useDiscovery } from "@/hooks/useDiscovery";
import { SwipeStack } from "@/components/discovery/SwipeStack";
import { MatchModal } from "@/components/discovery/MatchModal";
import { ProfileDetail } from "@/components/discovery/ProfileDetail";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { MagnifyingGlass } from "@phosphor-icons/react";
import type { Candidate } from "@/types";

export default function DiscoverPage() {
  const router = useRouter();
  const { candidates, loading, exhausted, fetchCandidates, swipe } = useDiscovery();

  const [matchModal, setMatchModal] = useState<{
    isOpen: boolean;
    candidate: Candidate | null;
    matchId: string | null;
  }>({ isOpen: false, candidate: null, matchId: null });

  const [profileDetail, setProfileDetail] = useState<{
    isOpen: boolean;
    candidate: Candidate | null;
  }>({ isOpen: false, candidate: null });

  useEffect(() => {
    fetchCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (candidates.length <= 2 && !loading && !exhausted) {
      fetchCandidates();
    }
  }, [candidates.length, loading, exhausted, fetchCandidates]);

  const handleMatch = useCallback((matchId: string, candidate: Candidate) => {
    setMatchModal({ isOpen: true, candidate, matchId });
  }, []);

  const handleTap = useCallback((candidate: Candidate) => {
    setProfileDetail({ isOpen: true, candidate });
  }, []);

  if (loading && candidates.length === 0) {
    return <LoadingSpinner size={48} className="flex-1" />;
  }

  if (exhausted && candidates.length === 0) {
    return (
      <EmptyState
        icon={MagnifyingGlass}
        title="No one new around"
        description="Check back later for new people"
        className="flex-1"
      />
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center px-4 pt-2 pb-4">
      <SwipeStack
        candidates={candidates}
        onSwipe={swipe}
        onMatch={handleMatch}
        onTap={handleTap}
      />

      <ProfileDetail
        candidate={profileDetail.candidate}
        isOpen={profileDetail.isOpen}
        onClose={() => setProfileDetail({ isOpen: false, candidate: null })}
        onSwipe={async (action) => {
          const target = profileDetail.candidate;
          if (!target) return;
          const result = await swipe(target.userId, action);
          if (result.matched && result.matchId) {
            handleMatch(result.matchId, target);
          }
        }}
      />

      <MatchModal
        isOpen={matchModal.isOpen}
        candidate={matchModal.candidate}
        matchId={matchModal.matchId}
        onChat={() => {
          setMatchModal((m) => ({ ...m, isOpen: false }));
          if (matchModal.matchId) router.push(`/chat/${matchModal.matchId}`);
        }}
        onContinue={() => setMatchModal((m) => ({ ...m, isOpen: false }))}
      />
    </div>
  );
}
