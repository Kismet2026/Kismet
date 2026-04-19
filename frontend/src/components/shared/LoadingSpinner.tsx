"use client";

import { cn } from "@/lib/utils";
import { SpinnerGap } from "@phosphor-icons/react";

interface LoadingSpinnerProps {
  size?: number;
  className?: string;
}

export function LoadingSpinner({ size = 32, className }: LoadingSpinnerProps) {
  return (
    <div className={cn("flex items-center justify-center", className)}>
      <SpinnerGap
        size={size}
        className="animate-spin text-primary"
        weight="bold"
      />
    </div>
  );
}
