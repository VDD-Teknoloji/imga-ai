// Veri kaynağı ikon eşlemesi (home-liveliness, 2026-09-02).
//
// `source` — reviews tablosundaki serbest metin İŞ BOYUTU (bkz.
// reviews/page.tsx satır 201-205 notu: "source_types" ingest yöntemiyle
// KARIŞTIRILMAMALI). Tenant'lar bu kolona istediği metni yazabilir
// ("E-posta", "Web Sitesi", "Twitter", "Mağaza"…) — kapalı bir enum
// YOK, bu yüzden anahtar kelime eşleşmesiyle en yakın ikona düşülür;
// hiçbir kalıp tutmazsa HelpCircle (data-source-strip.tsx'teki
// sourceLabel() ile aynı ham-değer felsefesi, burada yalnız ikon için).
//
// `sourceIcon()`i render içinde DOĞRUDAN JSX etiketi olarak kullanmayın
// (`const Icon = sourceIcon(v); <Icon/>`) — React Compiler'ın
// react-hooks/static-components kuralı bunu "render sırasında bileşen
// üretimi" sayıp hata verir (bkz. category-icons.ts'teki aynı WHY
// notu). Satır içi kullanım: `sourceIconIndex(value)` bir SAYI döner
// (JSX etiketi değil, güvenli), ardından `SOURCE_ICONS[idx] ??
// HelpCircle` düz bir dizi indekslemesidir.

import {
  Globe,
  HelpCircle,
  Mail,
  MessageSquare,
  Phone,
  Star,
  Store,
  type LucideIcon,
} from "lucide-react";

import { XLogo } from "@/components/icons/x-logo";

const SOURCE_PATTERNS: readonly RegExp[] = [
  /mail|e-?posta|eposta/,
  /twitter|\bx\b/,
  /widget|feedback|form|anket/,
  /store|mağaza|magaza|shop/,
  /phone|telefon|çağrı|cagri|call ?center/,
  /star|app ?store|google ?play|yorum ?sitesi|review/,
  /portal|web|site|dashboard|panel/,
];

// SOURCE_PATTERNS ile aynı sırada (indeks eşlemesi) — ikisi ayrı
// dizilerdir ki sourceIconIndex() JSX etiketi DEĞİL bir sayı döner.
export const SOURCE_ICONS: readonly LucideIcon[] = [
  Mail,
  XLogo,
  MessageSquare,
  Store,
  Phone,
  Star,
  Globe,
];

/** Eşleşen kalıbın SOURCE_ICONS içindeki indeksi, yoksa -1. Sayı
 *  döndüğü için render içinde çağrılması güvenlidir (dosya üstü not);
 *  yalnız SONUÇ bir JSX etiketine doğrudan atanmamalı. */
export function sourceIconIndex(value: string): number {
  const v = value.trim().toLowerCase();
  if (!v) return -1;
  for (let i = 0; i < SOURCE_PATTERNS.length; i++) {
    if (SOURCE_PATTERNS[i]!.test(v)) return i;
  }
  return -1;
}

/** JSX-dışı kullanım için ince sarmalayıcı (dosya üstü not) — render
 *  içinde `<Icon/>` üretecekseniz sourceIconIndex + SOURCE_ICONS'u
 *  satır içi kullanın. */
export function sourceIcon(value: string): LucideIcon {
  const idx = sourceIconIndex(value);
  return idx === -1 ? HelpCircle : SOURCE_ICONS[idx]!;
}
