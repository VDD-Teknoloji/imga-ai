import {
  Bell,
  Building2,
  ClipboardList,
  Code2,
  Compass,
  Cpu,
  FileBarChart,
  FileSearch,
  History,
  LayoutDashboard,
  ListChecks,
  Send,
  Settings,
  Sparkles,
  Ticket,
  TrendingUp,
  Upload,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * Single source of truth for sidebar navigation. The order here is
 * the order rendered. `roles` filters items by the user's active
 * tenant role; an empty array means "anyone with a tenant".
 */
export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { label: "Panel", href: "/", icon: LayoutDashboard },
  { label: "Ticket'lar", href: "/tickets", icon: Ticket },
  { label: "Analiz", href: "/analyze", icon: Sparkles },
  { label: "Toplu Yükleme", href: "/analyze/upload", icon: Upload },
  { label: "Analizler", href: "/reviews", icon: FileSearch },
  { label: "Raporlar", href: "/reports", icon: FileBarChart },
  { label: "İçgörüler", href: "/insights", icon: TrendingUp },
  { label: "Strateji", href: "/strategy", icon: Compass },
  { label: "Brifing", href: "/executive-briefing", icon: ClipboardList },
  { label: "Aksiyonlar", href: "/action-items", icon: ListChecks },
  { label: "Uyarılar", href: "/trend-alerts", icon: Bell },
  // Sprint 9.0.5-B B — manuel SLA webhook dispatch kuyruğu. Sidebar
  // badge'i pending count'u live tutuyor (use-pending-webhooks hook
  // 30s polling).
  { label: "Bekleyen Bildirimler", href: "/pending-webhooks", icon: Send },
  { label: "Ayarlar", href: "/settings", icon: Settings },
];

/**
 * Sprint 7.7.4 — admin-only nav. Rendered as a separate "YÖNETİM"
 * section under the main NAV_ITEMS, gated entirely behind
 * `user.is_super_admin === true` so non-admins never see the
 * heading at all.
 *
 * Sprint 9.4 I — three Sprint 9.3 governance pages added so they
 * stop being URL-only secrets. Order: tenant management first
 * (the established admin entry-point), then the three observability
 * surfaces (LLM audit, decision audit, prompt templates) in the
 * order an admin typically walks them — what the LLM did, what the
 * humans decided, what prompts shaped both.
 */
export const ADMIN_NAV_ITEMS: ReadonlyArray<NavItem> = [
  { label: "Tenant'lar", href: "/admin/tenants", icon: Building2 },
  { label: "LLM Denetimi", href: "/admin/llm-audit", icon: Cpu },
  { label: "Karar Geçmişi", href: "/admin/decision-audit", icon: History },
  {
    label: "Prompt Şablonları",
    href: "/admin/prompt-templates",
    icon: Code2,
  },
];
