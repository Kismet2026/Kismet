"use client";

import { Component, type ReactNode } from "react";
import { WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center gap-3 py-16 px-4 text-center">
          <WarningCircle size={48} className="text-destructive" weight="thin" />
          <h3 className="text-lg font-medium text-foreground">
            Something went wrong
          </h3>
          <p className="text-sm text-muted-foreground max-w-xs">
            {this.state.error?.message ?? "An unexpected error occurred."}
          </p>
          <Button
            variant="outline"
            onClick={() => this.setState({ hasError: false, error: undefined })}
            className="mt-2"
          >
            Try again
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
