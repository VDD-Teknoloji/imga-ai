// Kategori ikon + ton kayıt defteri (home-liveliness, 2026-09-02).
//
// 9 global kategori kodu (packages/imga-core/src/imga_core/categories/
// taxonomy.py — GLOBAL_CATEGORY_CODES) sabit bir ikon + soft-tint renk
// çiftine eşlenir. Kurum-özel (custom) kategoriler bu listede yoktur —
// onlar için kod DETERMİNİSTİK biçimde küçük bir yedek paletine
// hash'lenir (aynı kod her zaman aynı ikon+rengi alır), böylece HİÇBİR
// kategori ikonsuz kalmaz. Ton string'leri (`bg-x-500/15 text-x-700
// dark:text-x-400`) ticket-helpers.ts'teki mevcut kaynaştırılmış-durum
// paletiyle aynı kalıbı izler.
//
// ÖNEMLİ — çağıranlar (bileşenler) JSX etiketi olarak kullanacaksa
// `categoryIcon(code)`in KENDİSİNİ değil, aşağıdaki CATEGORY_ICON_MAP /
// CATEGORY_ICON_FALLBACK çiftini + categoryIconFallbackIndex()'i satır
// içi kullanmalı (`MAP[code] ?? FALLBACK[idx]`) — React Compiler'ın
// react-hooks/static-components kuralı, bir bileşen fonksiyonu içinde
// render sırasında ÇAĞRILAN bir fonksiyonun sonucu doğrudan JSX etiketi
// olarak kullanılırsa hata verir ("Cannot create components during
// render"), çünkü derleyici çağrılan fonksiyonun saf/kararlı olduğunu
// kanıtlayamaz. Düz obje/array indeksleme (ComputedLoad) bu kurala
// takılmaz — ticket-timeline.tsx'teki `cond ? A : B` deseniyle aynı
// mantık, yalnız iki dallı yerine tablo tabanlı. `categoryIcon()`/
// `experienceIcon()` fonksiyonları JSX-dışı kullanım için (örn. bir
// yardımcı fonksiyona referans geçirmek) hâlâ dursun diye export
// ediliyor — sadece render'da doğrudan JSX etiketi YAPMAYIN.

import {
  Boxes,
  Headset,
  Hash,
  HelpCircle,
  Layers,
  Megaphone,
  Monitor,
  Package,
  PackageCheck,
  Puzzle,
  Receipt,
  ShoppingCart,
  Tag,
  Truck,
  Undo2,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface CategoryTone {
  /** Yumuşak dolgu — ikon dairesinin arkaplanı. */
  bg: string;
  /** İkon + (gerekirse) metin rengi. */
  fg: string;
}

export const CATEGORY_ICON_MAP: Readonly<Record<string, LucideIcon>> = {
  kargo: Truck,
  faturalama: Receipt,
  urun_kalitesi: PackageCheck,
  musteri_hizmetleri: Headset,
  iade: Undo2,
  teknik_destek: Wrench,
  siparis_sureci: ShoppingCart,
  pazarlama: Megaphone,
  belirsiz: HelpCircle,
};

// Kurum-özel kategori kodu bilinen listede yoksa buraya hash'lenir.
export const CATEGORY_ICON_FALLBACK: readonly LucideIcon[] = [Boxes, Tag, Layers, Puzzle, Hash];

const KNOWN_TONE: Readonly<Record<string, CategoryTone>> = {
  kargo: { bg: "bg-blue-500/15", fg: "text-blue-700 dark:text-blue-400" },
  faturalama: { bg: "bg-amber-500/15", fg: "text-amber-700 dark:text-amber-400" },
  urun_kalitesi: { bg: "bg-emerald-500/15", fg: "text-emerald-700 dark:text-emerald-400" },
  musteri_hizmetleri: { bg: "bg-indigo-500/15", fg: "text-indigo-700 dark:text-indigo-400" },
  iade: { bg: "bg-rose-500/15", fg: "text-rose-700 dark:text-rose-400" },
  teknik_destek: { bg: "bg-cyan-500/15", fg: "text-cyan-700 dark:text-cyan-400" },
  siparis_sureci: { bg: "bg-orange-500/15", fg: "text-orange-700 dark:text-orange-400" },
  pazarlama: { bg: "bg-violet-500/15", fg: "text-violet-700 dark:text-violet-400" },
  // "belirsiz" bilinçli olarak nötr gri — bir kategori DEĞİL, henüz
  // sınıflandırılamamış bir kova; canlı bir renk yanlış vurgu yapar.
  belirsiz: { bg: "bg-muted", fg: "text-muted-foreground" },
};

const FALLBACK_TONES: readonly CategoryTone[] = [
  { bg: "bg-blue-500/15", fg: "text-blue-700 dark:text-blue-400" },
  { bg: "bg-violet-500/15", fg: "text-violet-700 dark:text-violet-400" },
  { bg: "bg-amber-500/15", fg: "text-amber-700 dark:text-amber-400" },
  { bg: "bg-teal-500/15", fg: "text-teal-700 dark:text-teal-400" },
  { bg: "bg-rose-500/15", fg: "text-rose-700 dark:text-rose-400" },
  { bg: "bg-indigo-500/15", fg: "text-indigo-700 dark:text-indigo-400" },
  { bg: "bg-emerald-500/15", fg: "text-emerald-700 dark:text-emerald-400" },
  { bg: "bg-orange-500/15", fg: "text-orange-700 dark:text-orange-400" },
];

/** Basit djb2-benzeri karma — yalnız deterministik palet seçimi için;
 *  kriptografik değil, tekrarlanabilir olması yeterli. */
function hashCode(value: string): number {
  let h = 5381;
  for (let i = 0; i < value.length; i++) {
    h = (h * 33 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/** CATEGORY_ICON_FALLBACK içindeki indeks — sayı döner (bileşen bunu
 *  JSX etiketi değil bir INDEX olarak kullandığı için static-components
 *  kuralına takılmaz), satır içi kullanım için: `CATEGORY_ICON_MAP[code]
 *  ?? CATEGORY_ICON_FALLBACK[categoryIconFallbackIndex(code)]`. */
export function categoryIconFallbackIndex(code: string): number {
  return hashCode(code) % CATEGORY_ICON_FALLBACK.length;
}

/** Her kategori kodu için bir ikon — bilinen 9 global koddan biri
 *  değilse (kurum-özel kategori) koda göre deterministik bir yedek
 *  seçilir; hiçbir kategori ikonsuz kalmaz. JSX-DIŞI kullanım için
 *  (dosya üstü not) — render içinde `<Icon />` üretecekseniz
 *  CATEGORY_ICON_MAP/CATEGORY_ICON_FALLBACK'i satır içi kullanın. */
export function categoryIcon(code: string): LucideIcon {
  return CATEGORY_ICON_MAP[code] ?? CATEGORY_ICON_FALLBACK[categoryIconFallbackIndex(code)]!;
}

/** Her kategori kodu için soft-tint arkaplan + ikon/metin rengi çifti
 *  — categoryIcon ile aynı bilinen/yedek ayrımını izler. Yalnız string
 *  döner (className), JSX etiketi DEĞİL — static-components kuralına
 *  hiç takılmaz, doğrudan render içinde çağrılabilir. */
export function categoryTone(code: string): CategoryTone {
  return KNOWN_TONE[code] ?? FALLBACK_TONES[hashCode(code) % FALLBACK_TONES.length]!;
}

export type ExperienceKind = "dijital" | "operasyonel";

/** experience-breakdown-cards.tsx için tek ikon kaynağı (görev
 *  talimatı: Smartphone/Monitor dijital, Package/Store operasyonel
 *  için kabul edilebilir; Monitor/Package kartların markalı
 *  gradyanıyla en net kontrastı veriyor). Sabit iki anahtarlı bir
 *  obje olduğundan render'da JSX etiketi için doğrudan
 *  `EXPERIENCE_ICON_MAP[kind]` kullanılabilir (dosya üstü not). */
export const EXPERIENCE_ICON_MAP: Readonly<Record<ExperienceKind, LucideIcon>> = {
  dijital: Monitor,
  operasyonel: Package,
};

/** JSX-dışı kullanım için ince sarmalayıcı (dosya üstü not). */
export function experienceIcon(kind: ExperienceKind): LucideIcon {
  return EXPERIENCE_ICON_MAP[kind];
}
