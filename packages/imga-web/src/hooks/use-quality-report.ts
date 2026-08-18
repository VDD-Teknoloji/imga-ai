"use client";

// 2026-08-18 (Dalga 3, WS2) — toplu yükleme kalite raporu.
//
// GET LLM'e hiç dokunmaz — job kolonlarından sayaçlar + bu job'un
// satırlarından en çok tekrarlanan metinler + çalışan bazlı kırılım.
// POST .../generate tek seferlik bir LLM özeti üretir ve backend'de
// job satırına KALICI olarak cache'ler; ikinci çağrıda LLM'e hiç
// dokunmadan mevcut özeti döner (backend garantisi).
//
// Tipler burada yaşıyor (lib/types.ts'e dokunulmuyor — WS5 reviews
// ajanıyla eşzamanlı düzenleme riski) — use-root-cause.ts ile aynı
// yerel-tip deseni.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface QualityFlagCounts {
  duplicate: number;
  empty: number;
  informational: number;
  meaningless: number;
}

export interface RepeatedText {
  text_hash: string;
  count: number;
  sample_text: string;
}

export interface EnteredByBreakdown {
  entered_by: string | null;
  total: number;
  duplicate: number;
  empty: number;
  informational: number;
  meaningless: number;
}

export interface QualitySummary {
  assessment: string;
  model_provider: string;
  model_name: string;
  generated_at: string;
}

export interface QualityReport {
  job_id: string;
  total_rows: number;
  succeeded_rows: number;
  counts: QualityFlagCounts;
  top_repeated_texts: RepeatedText[];
  entered_by_breakdown: EnteredByBreakdown[];
  /** null = özet henüz üretilmedi (POST .../generate hiç çağrılmadı). */
  summary: QualitySummary | null;
}

function queryKey(jobId: string) {
  return ["batch-quality-report", jobId] as const;
}

/** ``jobId`` null iken hiç istek atılmaz (dialog kapalıyken boşuna
 *  çağrı yok — root-cause dialog deseniyle aynı). */
export function useQualityReport(jobId: string | null) {
  return useQuery<QualityReport>({
    queryKey: queryKey(jobId ?? ""),
    enabled: jobId !== null,
    queryFn: () =>
      apiRequest<QualityReport>(`/tenants/me/analyze/batch/${jobId}/quality-report`),
  });
}

export function useGenerateQualityReport() {
  const qc = useQueryClient();
  return useMutation<QualityReport, Error, string>({
    mutationFn: (jobId) =>
      apiRequest<QualityReport>(
        `/tenants/me/analyze/batch/${jobId}/quality-report/generate`,
        { method: "POST" },
      ),
    onSuccess: (data, jobId) => {
      qc.setQueryData(queryKey(jobId), data);
    },
  });
}
