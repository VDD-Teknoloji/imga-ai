"use client";

import { PanelLeft } from "lucide-react";

import { SidebarNav } from "@/components/layout/sidebar-nav";
import { TenantSwitcher } from "@/components/layout/tenant-switcher";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useUiStore } from "@/lib/ui-store";
import { cn } from "@/lib/utils";

interface SidebarProps {
  /** When `mobile` is set the sidebar renders inside the Sheet body
   * — no width transitions, always full-width inside the Sheet,
   * and clicking a nav item closes the Sheet via onNavigate. */
  variant: "desktop" | "mobile";
  /** Mobile-only: invoked when the user follows a nav link, so the
   * parent Sheet can close itself. */
  onNavigate?: () => void;
}

/**
 * Persistent left rail. Three rows:
 *
 *   1. Header     — tenant switcher + the desktop collapse toggle
 *   2. Nav        — link list (Dashboard / Tickets / Settings)
 *   3. Footer     — user avatar + dropdown (logout)
 *
 * The desktop variant honours the `sidebarCollapsed` ui-store flag
 * (240px expanded → 60px icon-only). The mobile variant is fixed at
 * 240px because it lives inside a Sheet that the user can dismiss.
 */
export function Sidebar({ variant, onNavigate }: SidebarProps) {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);

  // Mobile sheet always renders the expanded version.
  const isCollapsed = variant === "desktop" && collapsed;

  return (
    <aside
      aria-label="Kenar çubuğu"
      className={cn(
        "bg-sidebar text-sidebar-foreground flex h-full flex-col",
        variant === "desktop" && "border-r transition-[width] duration-200",
        variant === "desktop" && (isCollapsed ? "w-[60px]" : "w-[240px]"),
        variant === "mobile" && "w-full",
      )}
    >
      <header
        className={cn(
          "bg-sidebar sticky top-0 z-10 flex shrink-0 items-center gap-2 p-2",
          isCollapsed ? "flex-col" : "flex-row",
        )}
      >
        <div className={cn("min-w-0 flex-1", isCollapsed && "w-full flex-none")}>
          <TenantSwitcher collapsed={isCollapsed} />
        </div>

        {variant === "desktop" ? (
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleSidebar}
            aria-label={isCollapsed ? "Kenar çubuğunu genişlet" : "Kenar çubuğunu daralt"}
            className="size-8 shrink-0"
          >
            <PanelLeft
              className={cn(
                "size-4 transition-transform duration-200",
                isCollapsed && "rotate-180",
              )}
              aria-hidden
            />
          </Button>
        ) : null}
      </header>

      <Separator />

      <div className="flex-1 overflow-y-auto py-2">
        <SidebarNav collapsed={isCollapsed} onNavigate={onNavigate} />
      </div>

      <Separator />

      <footer className="bg-sidebar sticky bottom-0 z-10 p-2">
        <UserMenu collapsed={isCollapsed} />
      </footer>
    </aside>
  );
}
