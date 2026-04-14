"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { BottomTabBar } from "@/components/layout/BottomTabBar";
import { useHeartbeat } from "@/hooks/usePresence";

const HIDE_TAB_BAR = ["/onboarding", "/chat"];

export default function MainLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const showTabBar = !HIDE_TAB_BAR.some((p) => pathname.startsWith(p));
  useHeartbeat();

  return (
    <AuthGuard>
      <div className="flex flex-col min-h-dvh">
        <main className={`flex-1 ${showTabBar ? "pb-16" : ""}`}>
          {children}
        </main>
        {showTabBar && <BottomTabBar />}
      </div>
    </AuthGuard>
  );
}
