import {
  ArrowLeftRight,
  Bell,
  Building2,
  ClipboardList,
  Code2,
  Compass,
  Cpu,
  FileBarChart,
  FileSearch,
  Gauge,
  History,
  LayoutDashboard,
  ListChecks,
  ScrollText,
  Send,
  Settings,
  Sparkles,
  Ticket,
  TrendingUp,
  Upload,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { XLogo } from "@/components/icons/x-logo";

/**
 * Single source of truth for sidebar navigation.
 *
 * Sprint 9.6 redesign: from a flat 13-item list to 3 grouped
 * sections so the C-level reach-for-first surfaces sit at the top
 * (no header — the implicit primary group), then the analyst and
 * operator workflows fall into named sections below. The eye scans
 * one group at a time instead of one long flat list.
 */
export interface NavItem {
  /** i18n anahtarı (ör. "shell.nav.tickets"); sidebar-nav.tsx render
   *  sırasında t() ile çözer — bu dosya client bileşeni değil. */
  label: string;
  href: string;
  icon: LucideIcon;
  /** Sprint 9.9 — Madde 3 (UML feedback): bazı item'lar görsel
   *  olarak kendi mini-grubu gibi durmalı (Manuel Analiz + Toplu
   *  Yükleme = "Veri Yükle"). `subgroup` aynı stringi taşıyan
   *  ardışık item'ları sidebar'da hafifçe indent + üst etiketle
   *  bir alt-grup haline getiriyor. Boş bırakılırsa item bağımsız
   *  bir satır olarak render edilir. */
  subgroup?: string;
  /** Sprint 13 — rol eşiği. Boş: tüm üyeler görür.
   *  "write" = tenant_admin | analyst; "admin" = tenant_admin;
   *  "super" = yalnız super admin. Backend require_role matrisinin
   *  aynası — kullanıcıya 403 yiyeceği kapı gösterilmez. */
  minRole?: "write" | "admin" | "super";
}

export interface NavSection {
  /** Section heading i18n anahtarı (sidebar-nav.tsx t() ile çözer).
   *  Empty string for the first (no-header) group — primary
   *  executive surfaces; boş string başlıksız kalır. */
  heading: string;
  items: ReadonlyArray<NavItem>;
}

// Sprint 9.8 — UML test feedback rename'leri:
//   * Madde 4: "Analizler" → "Analiz Arşivi" (Manuel Analiz ile karışmasın)
//   * Madde 6: "Brifing" → "Yönetici Özeti" (menü + sayfa başlığı tekil)
//   * Madde 11: "Override Katmanları" → "Kural Katmanları" (Türkçe — insights tab'da)
//   * Madde 13: support-ticket etiketi standart terim olarak "Ticket'lar"
//   * Madde 5: "Bekleyen Bildirimler" admin-only oldu — sidebar-nav buna göre filtreliyor
export const NAV_SECTIONS: ReadonlyArray<NavSection> = [
  // Yönetici — C-level reach-for-first surfaces. No section header;
  // these are the implicit primary group, like the home-screen dock
  // on iOS.
  {
    heading: "",
    items: [
      { label: "shell.nav.dashboard", href: "/", icon: LayoutDashboard },
      // Madde 6 — "Brifing" → "Yönetici Özeti"
      {
        label: "shell.nav.executiveSummary",
        href: "/executive-briefing",
        icon: ClipboardList,
      },
      { label: "shell.nav.actionItems", href: "/action-items", icon: ListChecks },
      { label: "shell.nav.trendAlerts", href: "/trend-alerts", icon: Bell },
      { label: "shell.nav.strategy", href: "/strategy", icon: Compass },
    ],
  },
  // Analitik — analyst persona's daily surfaces. Madde 3 not'u:
  // Operasyon altına Manuel Analiz + Toplu Yükleme alındı; Analiz
  // Arşivi (eski "Analizler") burada kalıyor çünkü ana iş "arşiv
  // gezme" — analyst persona.
  {
    heading: "shell.nav.section.analytics",
    items: [
      { label: "shell.nav.insights", href: "/insights", icon: TrendingUp },
      // WS4 (2026-08-18) — dönem karşılaştırma, İçgörüler'in yanında.
      { label: "shell.nav.compare", href: "/compare", icon: ArrowLeftRight },
      // Madde 4 — "Analizler" → "Analiz Arşivi"
      { label: "shell.nav.reviewArchive", href: "/reviews", icon: FileSearch },
      { label: "shell.nav.reports", href: "/reports", icon: FileBarChart },
    ],
  },
  // Operasyon — ticket queue + manual/batch ingestion. Madde 13:
  // support-ticket etiketi standart terim olarak "Ticket'lar". Madde 5:
  // Bekleyen Bildirimler buradan çıkarıldı — sadece super_admin'e
  // ADMIN_NAV_ITEMS altında gösteriliyor.
  //
  // Sprint 9.9 — Madde 3: Manuel Analiz + Toplu Yükleme görsel
  // olarak "Veri Yükle" mini-grubu altında, hafif indent ile.
  // Operasyon altında "data ingestion"ın bir alt-konu olduğunu
  // sezgisel veriyor.
  {
    heading: "shell.nav.section.operations",
    items: [
      { label: "shell.nav.tickets", href: "/tickets", icon: Ticket },
      {
        label: "shell.nav.manualAnalysis",
        href: "/analyze",
        icon: Sparkles,
        subgroup: "shell.nav.subgroup.dataUpload",
        minRole: "write",
      },
      {
        label: "shell.nav.batchUpload",
        href: "/analyze/upload",
        icon: Upload,
        subgroup: "shell.nav.subgroup.dataUpload",
        minRole: "write",
      },
      {
        label: "shell.nav.twitterImport",
        href: "/analyze/twitter",
        icon: XLogo,
        subgroup: "shell.nav.subgroup.dataUpload",
        minRole: "write",
      },
    ],
  },
  // Settings alone — no own heading, just stays last with a divider
  // before it (rendered by sidebar-nav). Avoids a 1-item section
  // labeled "Yönetim" that crowds the rail.
  {
    heading: "",
    items: [
      {
        label: "shell.nav.settings",
        href: "/settings",
        icon: Settings,
        minRole: "admin",
      },
    ],
  },
];

/**
 * Sprint 7.7.4 — admin-only nav. Rendered as a separate "YÖNETİM"
 * section under the main NAV_SECTIONS. NOT gated entirely behind
 * `is_super_admin` (that claim was stale — see the Sprint 13 note
 * below): the section heading shows for `tenant_admin` too, and each
 * item's own `minRole` decides visibility — "super" items (cross-
 * tenant: kurum CRUD'u, platform kullanım/maliyet, çapraz-kurum
 * denetim kaydı) stay super_admin-only, "admin" items (tenant-scoped
 * observability) are open to tenant_admin as well.
 *
 * Sprint 9.4 I — three Sprint 9.3 governance pages added: tenant
 * management first, then the three observability surfaces in the
 * order an admin typically walks them — what the LLM did, what the
 * humans decided, what prompts shaped both.
 *
 * 2026-08-20 (C1/C4 süper-admin envanteri) — iki yeni "super" öğe
 * (Platform Kullanımı, Denetim Kayıtları) tenants'ın hemen altına
 * eklendi: üçü birlikte çapraz-kurum platform görünümünü oluşturuyor,
 * ardından tenant-scoped "admin" gözlemlenebilirlik öğeleri geliyor.
 */
// Sprint 13 — bölüm artık tenant_admin'e de görünür: backend
// llm-audit / decision-audit / prompt-templates GET'lerine
// tenant_admin'i zaten kabul ediyordu ama nav yalnız super_admin'e
// gösteriyordu (hak sahibi kullanıcı kapıyı bulamıyordu). Kurum
// CRUD'u ise super_admin'de kalır.
export const ADMIN_NAV_ITEMS: ReadonlyArray<NavItem> = [
  {
    label: "shell.nav.tenants",
    href: "/admin/tenants",
    icon: Building2,
    minRole: "super",
  },
  {
    label: "shell.nav.platformUsage",
    href: "/admin/usage",
    icon: Gauge,
    minRole: "super",
  },
  {
    label: "shell.nav.auditLogs",
    href: "/admin/audit-logs",
    icon: ScrollText,
    minRole: "super",
  },
  {
    label: "shell.nav.llmAudit",
    href: "/admin/llm-audit",
    icon: Cpu,
    minRole: "admin",
  },
  {
    label: "shell.nav.decisionAudit",
    href: "/admin/decision-audit",
    icon: History,
    minRole: "admin",
  },
  {
    label: "shell.nav.promptTemplates",
    href: "/admin/prompt-templates",
    icon: Code2,
    minRole: "admin",
  },
  // Sprint 9.8 — Madde 5: Bekleyen Bildirimler içerik çok teknik
  // (SLA webhook dispatch detayı). Operasyon grubundan çıkarıldı,
  // admin-only oldu. Normal kullanıcı görmez; yönetici trend
  // ihlali yöneten kişi zaten gerekiyorsa erişir.
  {
    label: "shell.nav.pendingWebhooks",
    href: "/pending-webhooks",
    icon: Send,
    minRole: "admin",
  },
];

/**
 * Sprint 9.6 redesign — back-compat flattened export. Any caller
 * that still imports NAV_ITEMS gets a single ordered list (mostly
 * for tests / a11y audits that walk all routes). New code should
 * consume NAV_SECTIONS for grouped rendering.
 */
export const NAV_ITEMS: ReadonlyArray<NavItem> = NAV_SECTIONS.flatMap((s) => s.items);
