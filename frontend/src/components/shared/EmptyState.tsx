"use client";

import { cn } from "@/lib/utils";
import type { Icon } from "@phosphor-icons/react";

interface EmptyStateProps {
  icon?: Icon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon: IconComponent,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 py-16 px-4 text-center",
        className
      )}
    >
      {IconComponent && (
        <IconComponent size={48} className="text-muted-foreground" weight="thin" />
      )}
      <h3 className="text-lg font-medium text-foreground">{title}</h3>
      {description && (
        <p className="text-sm text-muted-foreground max-w-xs">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
