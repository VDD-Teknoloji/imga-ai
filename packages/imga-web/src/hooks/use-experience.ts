"use client";

// Deneyim dağılımı — /tenants/me/analytics/experience-distribution.
//
// Sınıflandırma revizyonu sonrası kovalar review.experience_type
// kolonundan sayılır. `experience_type` null olan (revizyon öncesi
// analiz edilmiş) satırlar için eski kategori-tabanlı yedeği BACKEND
// uygular; frontend hiçbir şeyi yeniden türetmez — gelen sayılar
// olduğu gibi gösterilir.
//
// `atanmamis`, ne alandan ne yedekten kovaya düşemeyen satırlardır
// (ör. 'belirsiz' kategori). Yüzde paydasına girmez; yalnız
// "yeniden analizle atanır" notunu besler.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface ExperienceBucket {
  total: number;
  negatif: number;
}

export interface ExperienceDistribution {
  dijital: ExperienceBucket;
  operasyonel: ExperienceBucket;
  atanmamis: ExperienceBucket;
}

export interface ExperienceDistributionFilters {
  /** YYYY-MM-DD (URL-dostu, timezone kayması yok). */
  date_from?: string;
  date_to?: string;
  /** 2026-08-18 (Dalga 3, WS2) — düşük kaliteli (bayraklı) satırları da
   *  dahil et. Varsayılan: hariç (backend default'uyla aynı). */
  include_flagged?: boolean;
}

// use-analytics.ts ile aynı genişletme: /tenants/me/analytics/* uçları
// datetime bekler, URL ise tarih taşır. Yarım yazılmış tarih filtreyi
// reddetmek yerine düşürülür (URL bar kullanıcı-düzenli).
function dateOnlyToLocalIso(
  value: string | undefined,
  endOfDay: boolean,
): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}${endOfDay ? "T23:59:59" : "T00:00:00"}`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export function useExperienceDistribution(
  filters: ExperienceDistributionFilters,
) {
  const params = new URLSearchParams();
  const from = dateOnlyToLocalIso(filters.date_from, false);
  const to = dateOnlyToLocalIso(filters.date_to, true);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (filters.include_flagged) params.set("include_flagged", "true");
  const query = params.toString();

  return useQuery<ExperienceDistribution>({
    queryKey: ["analytics-experience-distribution", query],
    queryFn: () =>
      apiRequest<ExperienceDistribution>(
        `/tenants/me/analytics/experience-distribution?${query}`,
      ),
    // Dönem filtresi değişince önceki veri görünür kalır (skeleton flash yok).
    placeholderData: keepPreviousData,
  });
}
