"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Compass, Heart, User } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

const tabs = [
  { href: "/discover", label: "Discover", icon: Compass, badge: false },
  { href: "/matches", label: "Matches", icon: Heart, badge: true },
  { href: "/profile", label: "Profile", icon: User, badge: false },
] as const;

export function BottomTabBar() {
  const pathname = usePathname();
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    async function fetchUnread() {
      try {
        const data = await api.get<{ count: number }>("/notifications/unread-count");
        setUnreadCount(data.count);
      } catch {
        // Mock for demo
        setUnreadCount(3);
      }
    }
    fetchUnread();
    const interval = setInterval(fetchUnread, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 border-t border-muted-foreground/30 bg-[#2a1624]">
      <div className="flex items-center justify-around h-16 max-w-md mx-auto">
        {tabs.map(({ href, label, icon: Icon, badge }) => {
          const isActive = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "relative flex flex-col items-center gap-0.5 px-4 py-2 transition-colors",
                isActive
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <div className="relative">
                <Icon
                  size={24}
                  weight={isActive ? "fill" : "regular"}
                />
                {badge && unreadCount > 0 && (
                  <div className="absolute -top-1.5 -right-2.5 min-w-[18px] h-[18px] rounded-full bg-primary flex items-center justify-center px-1">
                    <span className="text-[10px] font-bold text-primary-foreground">
                      {unreadCount > 9 ? "9+" : unreadCount}
                    </span>
                  </div>
                )}
              </div>
              <span className="text-[10px] font-medium">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
