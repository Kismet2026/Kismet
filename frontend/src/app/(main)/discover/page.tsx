"use client";

import { EmptyState } from "@/components/shared/EmptyState";
import { Compass } from "@phosphor-icons/react";

export default function DiscoverPage() {
  return (
    <EmptyState
      icon={Compass}
      title="Discover"
      description="Swipe cards coming in Phase 4"
      className="flex-1"
    />
  );
}
