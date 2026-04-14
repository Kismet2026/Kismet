"use client";

import { cn } from "@/lib/utils";

interface PresenceDotProps {
  isOnline: boolean;
  size?: "sm" | "md";
  className?: string;
}

export function PresenceDot({ isOnline, size = "sm", className }: PresenceDotProps) {
  return (
    <span
      className={cn(
        "rounded-full border-2 border-background",
        isOnline ? "bg-green-400" : "bg-muted-foreground/40",
        size === "sm" ? "w-3 h-3" : "w-4 h-4",
        className
      )}
    />
  );
}
