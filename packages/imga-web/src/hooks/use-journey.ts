"use client";

// Müşteri yolculuğu hunisi — /tenants/me/analytics/journey-distribution.
//
// Kovalar review.journey_stage kolonundan sayılır (migration 0052).
// Kategori yedeği YOK: aşaması olmayan satırlar `atanmamis` olarak ayrı
// gelir, yüzde paydasına girmez ve yalnız "yeniden analizle atanır"
// notunu besler. Frontend hiçbir şeyi yeniden türetmez.
//
// `sources` (CSV, ör. "twitter") tek kaynağın hunisini okur — Twitter
// çekimi sayfası bunu kullanır; `batch_job_id` tek yüklemeye daraltır.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { JourneyStage } from "@/lib/journey";

export interface JourneyStageRow {
  stage: JourneyStage | string;
  total: number;
  negatif: number;
}

export interface JourneyDistribution {
  /** Yalnız aşaması atanmış satırların toplamı (yüzde paydası). */
  total: number;
  /** Huni sırasında, her kod için dolu (0 dahil). */
  stages: JourneyStageRow[];
  atanmamis: { total: number; negatif: number };
}

export interface JourneyDistributionFilters {
  /** YYYY-MM-DD (URL-dostu). */
  date_from?: string;
  date_to?: string;
  include_flagged?: boolean;
  /** Review.source değerleri (CSV'ye katılır). */
  sources?: string[];
  batch_job_id?: string;
}

// use-experience.ts ile aynı genişletme: uç datetime bekler, URL tarih
// taşır; yarım yazılmış tarih düşürülür.
function dateOnlyToLocalIso(value: string | undefined, endOfDay: boolean): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}${endOfDay ? "T23:59:59" : "T00:00:00"}`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export function buildJourneyParams(filters: JourneyDistributionFilters): URLSearchParams {
  const params = new URLSearchParams();
  const from = dateOnlyToLocalIso(filters.date_from, false);
  const to = dateOnlyToLocalIso(filters.date_to, true);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (filters.include_flagged) params.set("include_flagged", "true");
  if (filters.sources?.length) params.set("sources", filters.sources.join(","));
  if (filters.batch_job_id) params.set("batch_job_id", filters.batch_job_id);
  return params;
}

export function useJourneyDistribution(filters: JourneyDistributionFilters, enabled = true) {
  const query = buildJourneyParams(filters).toString();
  return useQuery<JourneyDistribution>({
    queryKey: ["analytics-journey-distribution", query],
    enabled,
    queryFn: () =>
      apiRequest<JourneyDistribution>(`/tenants/me/analytics/journey-distribution?${query}`),
    placeholderData: keepPreviousData,
  });
}
