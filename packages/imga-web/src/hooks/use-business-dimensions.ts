// Sprint 9.3 B — business dimension config + breakdown hooks.
//
// 2026-08-20 (Insights "Boyutlar" sekmesi) — breakdown ucu artık tarih
// aralığı + include_flagged alıyor ve dimension evreni entered_by /
// source'u da kapsıyor (Ticket'ın iki sabit alanı). Bu ikisi
// settings/business-dimensions'ta KONFİGÜRE EDİLEMEZ (her zaman sabit
// i18n etiketiyle gösterilir), bu yüzden config CRUD'ının kullandığı
// dört değerli ``DimensionKey``'e eklenmedi — ayrı bir superset tipi
// (``BreakdownDimensionKey``) var ki settings sayfası yanlışlıkla
// entered_by/source için upsert/delete sunmasın.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export type DimensionKey =
  | "business_segment"
  | "product_line"
  | "channel"
  | "customer_tier";

/** Boyutlar tab / cohort seçicisi gibi salt-okunur analitik yüzeylerin
 *  sunduğu TÜM boyut evreni: 4 konfigüre-edilebilir iş boyutu artı
 *  Ticket'ın iki sabit alanı (entered_by, source). Yalnız analitik
 *  okuma tarafında (breakdown, dimension-values) kullanılır — config
 *  CRUD hâlâ dar ``DimensionKey``'e bağlı. */
export type BreakdownDimensionKey = DimensionKey | "entered_by" | "source";

/** ``/business-dimensions/{dimension}/breakdown`` ucunun kabul ettiği
 *  metric_key değerleri. "sentiment_distribution" bucket başına
 *  POZİTİF yüzdeyi doldurur (bkz. imga-api
 *  services/dimension_service.py — mevcut haliyle 3 metric_key
 *  destekliyor; negative_share/avg_sentiment bu sprint'te backend
 *  tarafında paralel ekleniyor) — UI'da "Pozitif %" etiketiyle
 *  gösterilir; 5 UI etiketi ↔ 5 metric_key birebir eşleşiyor. */
export type DimensionMetricKey =
  | "review_volume"
  | "sentiment_distribution"
  | "nps"
  | "negative_share"
  | "avg_sentiment";

export interface DimensionConfig {
  id: string;
  dimension: DimensionKey;
  display_label: string;
  enabled: boolean;
  allowed_values: string[];
  csv_column_mapping: string | null;
  created_at: string;
  updated_at: string;
}

export interface DimensionConfigUpsertRequest {
  display_label: string;
  enabled?: boolean;
  allowed_values?: string[];
  csv_column_mapping?: string | null;
}

export interface DimensionBreakdownBucket {
  value: string;
  count: number;
  /** Görev sözleşmesindeki ad ("metric_value"). Backend'in mevcut
   *  (pre-sprint) kodu bu alanı hâlâ ``score`` adıyla dönüyor — iki
   *  ajanlı eşzamanlı sprint'te hangi ad canlıya çıkacağı bu dosyadan
   *  doğrulanamadı. Her iki adı da okuyup normalize ediyoruz (bkz.
   *  bucketMetricValue) ki backend hangisini gönderirse göndersin
   *  grafik kırılmasın. */
  metric_value?: number | null;
  score?: number | null;
}

export interface DimensionBreakdown {
  metric_key: string;
  dimension: BreakdownDimensionKey;
  buckets: DimensionBreakdownBucket[];
  total_count: number;
  coverage_count: number;
}

/** ``metric_value`` öncelikli, yoksa ``score``'a düşer (bkz.
 *  DimensionBreakdownBucket yorumu). İkisi de sayı değilse null. */
export function bucketMetricValue(bucket: DimensionBreakdownBucket): number | null {
  const v = bucket.metric_value ?? bucket.score;
  return typeof v === "number" ? v : null;
}

const QUERY_KEY = ["business-dimensions"] as const;

export function useBusinessDimensions() {
  return useQuery<DimensionConfig[]>({
    queryKey: QUERY_KEY,
    queryFn: () =>
      apiRequest<DimensionConfig[]>("/tenants/me/business-dimensions"),
  });
}

export function useUpsertBusinessDimension() {
  const qc = useQueryClient();
  return useMutation<
    DimensionConfig,
    Error,
    { dimension: DimensionKey; body: DimensionConfigUpsertRequest }
  >({
    mutationFn: ({ dimension, body }) =>
      apiRequest<DimensionConfig>(
        `/tenants/me/business-dimensions/${dimension}`,
        { method: "PUT", body },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useDeleteBusinessDimension() {
  const qc = useQueryClient();
  return useMutation<void, Error, DimensionKey>({
    mutationFn: (dimension) =>
      apiRequest<void>(
        `/tenants/me/business-dimensions/${dimension}`,
        { method: "DELETE" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

// date_from/date_to URL'de YYYY-MM-DD taşır (url-state-patterns.md —
// ISO datetime DEĞİL); bu uç ISO datetime bekliyor. use-analytics.ts /
// use-reviews.ts ile aynı 1-günlük timezone-slide fix'i.
function dateOnlyToLocalIso(value: string | undefined, endOfDay: boolean): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}${endOfDay ? "T23:59:59" : "T00:00:00"}`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export interface DimensionBreakdownFilters {
  dimension: BreakdownDimensionKey | undefined;
  metric_key?: DimensionMetricKey;
  date_from?: string;
  date_to?: string;
  include_flagged?: boolean;
}

export function useDimensionBreakdown(filters: DimensionBreakdownFilters) {
  const {
    dimension,
    metric_key = "review_volume",
    date_from,
    date_to,
    include_flagged,
  } = filters;

  const params = new URLSearchParams();
  params.set("metric_key", metric_key);
  const isoFrom = dateOnlyToLocalIso(date_from, false);
  const isoTo = dateOnlyToLocalIso(date_to, true);
  if (isoFrom) params.set("date_from", isoFrom);
  if (isoTo) params.set("date_to", isoTo);
  // Backend default false — yalnız açık true'yu gönderiyoruz ki
  // varsayılan durumda query-cache anahtarı temiz kalsın.
  if (include_flagged) params.set("include_flagged", "true");
  const qs = params.toString();

  return useQuery<DimensionBreakdown>({
    queryKey: ["dimension-breakdown", dimension, qs],
    enabled: typeof dimension === "string",
    queryFn: () =>
      apiRequest<DimensionBreakdown>(
        `/tenants/me/business-dimensions/${dimension}/breakdown?${qs}`,
      ),
  });
}
