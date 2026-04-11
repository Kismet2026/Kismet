"use client";

import { EmptyState } from "@/components/shared/EmptyState";
import { User } from "@phosphor-icons/react";

export default function ProfilePage() {
  return (
    <EmptyState
      icon={User}
      title="Profile"
      description="Profile view coming in Phase 7"
      className="flex-1"
    />
  );
}
