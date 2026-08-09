"use client";

// Sprint 13.1 — kök neden analizi (drill-down 3. seviye).
//
// GET önce cache/DB'den okur; hiç üretilmemişse backend 404 döner —
// bu bir HATA değil, "henüz analiz yok" durumudur, o yüzden query
// 404'ü null'a çevirir ve retry etmez. POST üretimi tetikler.
//
// Tipler burada yaşıyor (lib/types.ts'e dokunulmuyor) —
// use-executive-overview.ts ile aynı yerel-tip deseni.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiRequest } from "@/lib/api-client";

export interface RootCauseItem {
  title: string;
  description: string;
  evidence_quotes: string[];
  affected_surface: string;
  suggested_action: string;
  share_estimate_pct: number | null;
}

export interface RootCausePayload {
  summary: string;
  root_causes: RootCauseItem[];
}

export interface RootCauseAnalysis {
  id: string;
  primary_category_code: string;
  perspective_code: string;
  date_from: string | null;
  date_to: string | null;
  review_count: number;
  model_provider: string;
  model_name: string;
  payload: RootCausePayload;
  created_at: string;
}

export interface RootCauseTarget {
  primary_category: string;
  perspective_code: string;
  date_from?: string;
  date_to?: string;
}

function queryString(target: RootCauseTarget): string {
  const params = new URLSearchParams();
  params.set("primary_category", target.primary_category);
  params.set("perspective_code", target.perspective_code);
  if (target.date_from) params.set("date_from", target.date_from);
  if (target.date_to) params.set("date_to", target.date_to);
  return params.toString();
}

/** En son üretilmiş analiz, yoksa `null`. `enabled=false` iken hiç
 *  istek atılmaz (dialog kapalıyken boşuna çağrı yok). */
export function useRootCause(target: RootCauseTarget | null) {
  const qs = target ? queryString(target) : "";
  return useQuery<RootCauseAnalysis | null>({
    queryKey: ["root-cause", qs],
    enabled: target !== null,
    // Backend 12 saat cache'liyor; frontend aynı pencereyi tutar.
    staleTime: 12 * 60 * 60 * 1000,
    retry: false,
    queryFn: async () => {
      try {
        return await apiRequest<RootCauseAnalysis>(`/tenants/me/insights/root-cause?${qs}`);
      } catch (err) {
        // 404 = "henüz üretilmemiş"; CTA gösterilecek, hata değil.
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
  });
}

export function useGenerateRootCause() {
  const qc = useQueryClient();
  return useMutation<RootCauseAnalysis, Error, RootCauseTarget>({
    mutationFn: (target) =>
      apiRequest<RootCauseAnalysis>("/tenants/me/insights/root-cause", {
        method: "POST",
        body: {
          primary_category: target.primary_category,
          perspective_code: target.perspective_code,
          date_from: target.date_from ?? null,
          date_to: target.date_to ?? null,
          // POST'u kullanıcı bilinçli olarak tetikler ("Analiz Oluştur" /
          // "Yeniden Oluştur"). 12 saatlik cache'e takılırsa buton
          // sessizce aynı sonucu döndürürdü — okuma zaten GET'te.
          force_refresh: true,
        },
      }),
    onSuccess: (data, target) => {
      qc.setQueryData(["root-cause", queryString(target)], data);
    },
  });
}
