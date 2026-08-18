"use client";

// WS4 (2026-08-18) — /compare sayfası: GET
// /tenants/me/analytics/period-comparison?a_from&a_to&b_from&b_to.
//
// Diğer analytics hook'larından (use-analytics.ts) tek farkı: bu uç
// dört alanı da `date` (YYYY-MM-DD) olarak bağlıyor, ISO datetime
// DEĞİL. dateOnlyToLocalIso genişletmesi burada YANLIŞ — 422 döner.
// Tarihler URL'den geldiği gibi, çıplak string olarak gider.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { NPSSummary } from "@/lib/types";

export interface ExperienceBucket {
  total: number;
  negatif: number;
}

export interface ExperienceDistribution {
  dijital: ExperienceBucket;
  operasyonel: ExperienceBucket;
  atanmamis: ExperienceBucket;
}

export interface PeriodStats {
  date_from: string;
  date_to: string;
  total_reviews: number;
  sentiment_counts: Record<string, number>;
  category_counts: Record<string, number>;
  nps: NPSSummary;
  experience: ExperienceDistribution;
  avg_sentiment_score: number | null;
}

/** "flat" hem fark tam sıfır olduğunda hem de bir/iki pencerede veri
 *  yokken döner (bkz. backend `_direction`) — "no signal" anlamı taşır. */
export type ComparisonDirection = "up" | "down" | "flat";

export interface PeriodComparisonDelta {
  total_reviews_diff: number;
  total_reviews_direction: ComparisonDirection;
  sentiment_pct_point_diff: Record<string, number>;
  category_pct_point_diff: Record<string, number>;
  nps_score_diff: number | null;
  nps_direction: ComparisonDirection;
  avg_sentiment_score_diff: number | null;
  avg_sentiment_direction: ComparisonDirection;
}

export interface PeriodComparisonResponse {
  period_a: PeriodStats;
  period_b: PeriodStats;
  delta: PeriodComparisonDelta;
}

export interface PeriodComparisonParams {
  aFrom: string;
  aTo: string;
  bFrom: string;
  bTo: string;
  /** Varsayılan false — düşük kaliteli (bayraklı) yorumlar hariç. */
  includeFlagged?: boolean;
}

function isValidYmd(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value));
}

/** Dört tarih de dolu VE her pencere içinde from<=to olmalı; backend
 *  aksi halde 400 döner. Yarım-düzenlenmiş URL'de istek atmak yerine
 *  sorguyu `enabled:false` ile boşta tutuyoruz. */
export function isComparisonRangeValid(params: PeriodComparisonParams): boolean {
  const { aFrom, aTo, bFrom, bTo } = params;
  if (![aFrom, aTo, bFrom, bTo].every(isValidYmd)) return false;
  return aFrom <= aTo && bFrom <= bTo;
}

export function usePeriodComparison(params: PeriodComparisonParams) {
  const valid = isComparisonRangeValid(params);
  const query = new URLSearchParams({
    a_from: params.aFrom,
    a_to: params.aTo,
    b_from: params.bFrom,
    b_to: params.bTo,
  });
  if (params.includeFlagged) query.set("include_flagged", "true");
  const qs = query.toString();

  return useQuery<PeriodComparisonResponse>({
    queryKey: ["analytics-period-comparison", qs],
    enabled: valid,
    queryFn: () =>
      apiRequest<PeriodComparisonResponse>(`/tenants/me/analytics/period-comparison?${qs}`),
    placeholderData: keepPreviousData,
  });
}

// --- tarih preset yardımcıları ---------------------------------------
//
// Backend'e giden format native <input type=date> ile aynı: YYYY-MM-DD,
// yerel (tarayıcı) takvimine göre. Hafta başlangıcı Pazartesi (ISO 8601 —
// TR konvansiyonu).

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

export function toYmd(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export interface DateRange {
  from: string;
  to: string;
}

/** Ayın 1'i → ayın son günü. `monthOffset=0` bu ay, `-1` geçen ay. */
export function monthRange(monthOffset: number, base: Date = new Date()): DateRange {
  const first = new Date(base.getFullYear(), base.getMonth() + monthOffset, 1);
  const last = new Date(base.getFullYear(), base.getMonth() + monthOffset + 1, 0);
  return { from: toYmd(first), to: toYmd(last) };
}

/** Belirli bir takvim ayı (1-indexed `month`) — ay gezgini için. */
export function monthRangeFor(year: number, month1to12: number): DateRange {
  const first = new Date(year, month1to12 - 1, 1);
  const last = new Date(year, month1to12, 0);
  return { from: toYmd(first), to: toYmd(last) };
}

/** Pazartesi → Pazar. `weekOffset=0` bu hafta, `-1` geçen hafta. */
export function weekRange(weekOffset: number, base: Date = new Date()): DateRange {
  const day = base.getDay(); // 0=Pazar .. 6=Cumartesi
  const isoDay = day === 0 ? 7 : day; // 1=Pazartesi .. 7=Pazar
  const monday = new Date(base.getFullYear(), base.getMonth(), base.getDate() - (isoDay - 1) + weekOffset * 7);
  const sunday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6);
  return { from: toYmd(monday), to: toYmd(sunday) };
}

/** 1-12 (Ocak..Aralık) → `compare.month.<n>` i18n anahtarı. Ay adları
 *  UI metni olduğu için sözlükte yaşar (compare.ts); burada yalnız
 *  anahtar üretimi. */
export function monthLabelKey(month1to12: number): string {
  return `compare.month.${month1to12}`;
}
