"use client";

// Sprint 13.2 — ana sayfa "kök neden önce" kartları.
//
// GET /tenants/me/insights/root-cause/overview: en yüksek negatif
// paya sahip ≤3 ana kategori + (varsa) o kategori için en son üretilmiş
// kök neden analizi — TEK round-trip (use-executive-overview.ts ile
// aynı "sayfa açılışında tek çağrı" ilkesi).
//
// Tipler burada yaşıyor (lib/types.ts'e dokunulmuyor) — use-root-cause.ts
// ile aynı yerel-tip deseni (paralel backend ajanı riski). Şekil o
// dosyadaki RootCauseAnalysis'ten kasıtlı olarak FARKLI: alan adı
// `causes` (payload.root_causes değil), `affected_surface` /
// `suggested_action` nullable — kontrat üretim öncesi (can_generate
// true, analysis null) kartlarla aynı endpoint'i paylaşıyor.
//
// date_from/date_to burada YYYY-MM-DD ham taşınır (ISO'ya genişletilmez)
// — backend `date` tipli query param bekliyor (tenant_insights.py'deki
// GET /root-cause ile aynı desen; use-executive-overview.ts'teki ISO
// genişletmesi BURAYA uygulanmaz).

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface RootCauseOverviewCauseItem {
  title: string;
  description: string;
  evidence_quotes: string[];
  affected_surface: string | null;
  suggested_action: string | null;
  share_estimate_pct: number | null;
  /** Sprint — çift katmanlı kart tasarımı (PO geri bildirimi): kısa,
   *  jargonsuz başlık. Eski kalıcı analizlerde yok — yoksa `title`e
   *  düşülür (root-cause-cards.tsx'teki `?? title`). */
  headline?: string | null;
  /** Aynı sprint: tek satırlık emir kipi aksiyon. Yoksa `suggested_action`e
   *  düşülür. */
  action_short?: string | null;
}

export interface RootCauseOverviewAnalysis {
  generated_at: string;
  review_count: number;
  date_from: string | null;
  date_to: string | null;
  summary: string;
  causes: RootCauseOverviewCauseItem[];
}

export interface RootCauseOverviewCard {
  primary_category_code: string;
  negative_count: number;
  share_pct: number;
  /** null: kategori için henüz otomatik alt kategori seçilmedi —
   *  `can_generate` de bu durumda false olur (üretim hedefsiz). */
  perspective_code: string | null;
  can_generate: boolean;
  analysis: RootCauseOverviewAnalysis | null;
}

export interface RootCauseOverviewResponse {
  cards: RootCauseOverviewCard[];
}

export interface RootCauseOverviewFilters {
  date_from?: string;
  date_to?: string;
}

export function useRootCauseOverview(filters: RootCauseOverviewFilters = {}, limit = 3) {
  const params = new URLSearchParams();
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  params.set("limit", String(limit));
  const query = params.toString();
  return useQuery<RootCauseOverviewResponse>({
    // qs queryKey'de — filtre değişince cache tek görüntüde donar
    // (executive-overview hook'undaki aynı gerekçe).
    queryKey: ["root-cause-overview", query],
    queryFn: () =>
      apiRequest<RootCauseOverviewResponse>(
        `/tenants/me/insights/root-cause/overview?${query}`,
      ),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}
