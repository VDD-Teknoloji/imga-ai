"use client";

import { PanelLeft } from "lucide-react";
import { useEffect } from "react";

import { ImgaMark, ImgaWordmark } from "@/components/brand/imga-logo";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { TenantSwitcher } from "@/components/layout/tenant-switcher";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useTranslation } from "@/lib/i18n/use-translation";
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
  const { t } = useTranslation();

  // Store her zaman "kapalı" başlar (SSR ile birebir — hydration
  // mismatch yok); kullanıcının kayıtlı "açık" tercihi mount
  // sonrası uygulanır ve mevcut width transition'ı ile genişler.
  useEffect(() => {
    useUiStore.getState().hydrateSidebar();
  }, []);

  // Mobile sheet always renders the expanded version.
  const isCollapsed = variant === "desktop" && collapsed;

  return (
    <aside
      aria-label={t("shell.sidebar.label")}
      className={cn(
        "bg-sidebar text-sidebar-foreground flex h-full flex-col",
        variant === "desktop" && "border-r transition-[width] duration-200",
        variant === "desktop" && (isCollapsed ? "w-[60px]" : "w-[240px]"),
        variant === "mobile" && "w-full",
      )}
    >
      <header
        className={cn(
          "bg-sidebar sticky top-0 z-10 flex shrink-0 flex-col gap-2 p-2",
        )}
      >
        {/* Sprint 10.2 — marka satırı. Lacivert rail'in tepesinde
            logo: açıkken wordmark (turuncu kare = i'nin noktası),
            kapalıyken arma. Rail'in kendisi marka laciverti olduğu
            için logo "uygulamanın imzası" gibi durur. */}
        <div
          className={cn(
            "flex items-center",
            isCollapsed ? "justify-center py-1.5" : "justify-between px-2 py-1.5",
          )}
        >
          {isCollapsed ? (
            <ImgaMark className="size-6 text-sidebar-foreground" />
          ) : (
            <>
              <span className="flex items-center gap-2.5">
                <ImgaMark className="size-6 text-sidebar-foreground" />
                <ImgaWordmark className="text-sidebar-foreground" />
              </span>
              {variant === "desktop" ? (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={toggleSidebar}
                  aria-label={t("shell.sidebar.collapse")}
                  className="hover:bg-sidebar-accent size-8 shrink-0 text-sidebar-foreground/70 hover:text-sidebar-foreground"
                >
                  <PanelLeft className="size-4" aria-hidden />
                </Button>
              ) : null}
            </>
          )}
        </div>

        {isCollapsed && variant === "desktop" ? (
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleSidebar}
            aria-label={t("shell.sidebar.expand")}
            className="hover:bg-sidebar-accent mx-auto size-8 shrink-0 text-sidebar-foreground/70 hover:text-sidebar-foreground"
          >
            <PanelLeft className="size-4 rotate-180" aria-hidden />
          </Button>
        ) : null}

        <div className={cn("min-w-0", isCollapsed && "w-full")}>
          <TenantSwitcher collapsed={isCollapsed} />
        </div>
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
