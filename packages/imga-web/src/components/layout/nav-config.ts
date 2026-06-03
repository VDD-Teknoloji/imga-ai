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
 * Single source of truth for sidebar navigation.
 *
 * Sprint 9.6 redesign: from a flat 13-item list to 3 grouped
 * sections so the C-level reach-for-first surfaces sit at the top
 * (no header — the implicit primary group), then the analyst and
 * operator workflows fall into named sections below. The eye scans
 * one group at a time instead of one long flat list.
 */
export interface NavItem {
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
}

export interface NavSection {
  /** Section heading shown above the items. Empty string for the
   *  first (no-header) group — primary executive surfaces. */
  heading: string;
  items: ReadonlyArray<NavItem>;
}

// Sprint 9.8 — UML test feedback rename'leri:
//   * Madde 4: "Analizler" → "Analiz Arşivi" (Manuel Analiz ile karışmasın)
//   * Madde 6: "Brifing" → "Yönetici Özeti" (menü + sayfa başlığı tekil)
//   * Madde 11: "Override Katmanları" → "Kural Katmanları" (Türkçe — insights tab'da)
//   * Madde 13: "Ticket'lar" → "Talepler" (CRM bağlamında daha doğal Türkçe)
//   * Madde 5: "Bekleyen Bildirimler" admin-only oldu — sidebar-nav buna göre filtreliyor
export const NAV_SECTIONS: ReadonlyArray<NavSection> = [
  // Yönetici — C-level reach-for-first surfaces. No section header;
  // these are the implicit primary group, like the home-screen dock
  // on iOS.
  {
    heading: "",
    items: [
      { label: "Panel", href: "/", icon: LayoutDashboard },
      // Madde 6 — "Brifing" → "Yönetici Özeti"
      {
        label: "Yönetici Özeti",
        href: "/executive-briefing",
        icon: ClipboardList,
      },
      { label: "Aksiyonlar", href: "/action-items", icon: ListChecks },
      { label: "Uyarılar", href: "/trend-alerts", icon: Bell },
      { label: "Strateji", href: "/strategy", icon: Compass },
    ],
  },
  // Analitik — analyst persona's daily surfaces. Madde 3 not'u:
  // Operasyon altına Manuel Analiz + Toplu Yükleme alındı; Analiz
  // Arşivi (eski "Analizler") burada kalıyor çünkü ana iş "arşiv
  // gezme" — analyst persona.
  {
    heading: "Analitik",
    items: [
      { label: "İçgörüler", href: "/insights", icon: TrendingUp },
      // Madde 4 — "Analizler" → "Analiz Arşivi"
      { label: "Analiz Arşivi", href: "/reviews", icon: FileSearch },
      { label: "Raporlar", href: "/reports", icon: FileBarChart },
    ],
  },
  // Operasyon — ticket queue + manual/batch ingestion. Madde 13:
  // "Ticket'lar" → "Talepler" — daha doğal Türkçe, CRM bağlamında
  // alışıldık. Madde 5: Bekleyen Bildirimler buradan çıkarıldı —
  // sadece super_admin'e ADMIN_NAV_ITEMS altında gösteriliyor.
  //
  // Sprint 9.9 — Madde 3: Manuel Analiz + Toplu Yükleme görsel
  // olarak "Veri Yükle" mini-grubu altında, hafif indent ile.
  // Operasyon altında "data ingestion"ın bir alt-konu olduğunu
  // sezgisel veriyor.
  {
    heading: "Operasyon",
    items: [
      { label: "Talepler", href: "/tickets", icon: Ticket },
      {
        label: "Manuel Analiz",
        href: "/analyze",
        icon: Sparkles,
        subgroup: "Veri Yükle",
      },
      {
        label: "Toplu Yükleme",
        href: "/analyze/upload",
        icon: Upload,
        subgroup: "Veri Yükle",
      },
    ],
  },
  // Settings alone — no own heading, just stays last with a divider
  // before it (rendered by sidebar-nav). Avoids a 1-item section
  // labeled "Yönetim" that crowds the rail.
  {
    heading: "",
    items: [{ label: "Ayarlar", href: "/settings", icon: Settings }],
  },
];

/**
 * Sprint 7.7.4 — admin-only nav. Rendered as a separate "YÖNETİM"
 * section under the main NAV_SECTIONS, gated entirely behind
 * `user.is_super_admin === true` so non-admins never see the
 * heading at all.
 *
 * Sprint 9.4 I — three Sprint 9.3 governance pages added: tenant
 * management first, then the three observability surfaces in the
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
  // Sprint 9.8 — Madde 5: Bekleyen Bildirimler içerik çok teknik
  // (SLA webhook dispatch detayı). Operasyon grubundan çıkarıldı,
  // admin-only oldu. Normal kullanıcı görmez; super_admin trend
  // ihlali yöneten kişi zaten gerekiyorsa erişir.
  {
    label: "Bekleyen Bildirimler",
    href: "/pending-webhooks",
    icon: Send,
  },
];

/**
 * Sprint 9.6 redesign — back-compat flattened export. Any caller
 * that still imports NAV_ITEMS gets a single ordered list (mostly
 * for tests / a11y audits that walk all routes). New code should
 * consume NAV_SECTIONS for grouped rendering.
 */
export const NAV_ITEMS: ReadonlyArray<NavItem> = NAV_SECTIONS.flatMap(
  (s) => s.items,
);
