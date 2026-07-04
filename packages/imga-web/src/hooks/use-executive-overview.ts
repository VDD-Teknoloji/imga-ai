// Sprint 10.0 — C-level dashboard tek-bakış hook'u.
//
// GET /tenants/me/executive/overview: duygu toplamları + en çok
// şikayet kategorisi + NPS + Müşterinin Sesi alıntıları + son
// SWOT/OKR/yönetici özeti snapshot'ları — TEK round-trip.
// Dashboard'un eski hali 6+ ayrı hook ile boyanıyordu; tek çağrı
// hem hızlı hem atomik bir görüntü verir.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface ExecutiveTopProblem {
  code: string;
  label: string;
  count: number;
  /** Tüm negatif yorumlar içindeki pay (0-100). */
  share_pct: number;
  /** Kategorinin en sert, anlamlı şikayet cümlesi (≤280 kr). */
  sample_text: string | null;
}

export interface ExecutiveQuote {
  id: string;
  text: string;
  sentiment_label: "POZITIF" | "NEGATIF" | "NÖTR";
  category_code: string;
  category_label: string;
  analyzed_at: string;
}

export interface ExecutiveBriefingSnapshot {
  id: string;
  headline: string;
  critical_insights: string[];
  period: string;
  created_at: string;
}

export interface ExecutiveSwotItem {
  title: string;
  description: string;
}

export interface ExecutiveSwotSnapshot {
  id: string;
  created_at: string;
  strengths: ExecutiveSwotItem[];
  weaknesses: ExecutiveSwotItem[];
  top_recommendation: {
    title: string;
    description: string;
    priority: string;
  } | null;
}

export interface ExecutiveOkrSnapshot {
  id: string;
  created_at: string;
  objectives: Array<{
    objective: string;
    key_results: Array<{
      text: string;
      metric: string;
      baseline: string;
      target: string;
    }>;
  }>;
}

export interface ExecutiveSentimentTrend {
  current_positive_pct: number;
  previous_positive_pct: number;
  /** Pozitif oranın puan cinsinden değişimi (son 30g vs önceki 30g). */
  delta_points: number;
}

export interface ExecutiveOverview {
  sentiment: {
    POZITIF: number;
    NEGATIF: number;
    "NÖTR": number;
    total: number;
  };
  /** null: önceki 30 günlük pencerede yorum yok (trend iddia edilmez). */
  trend: ExecutiveSentimentTrend | null;
  top_problems: ExecutiveTopProblem[];
  nps_score: number | null;
  voice_of_customer: ExecutiveQuote[];
  latest_briefing: ExecutiveBriefingSnapshot | null;
  latest_swot: ExecutiveSwotSnapshot | null;
  latest_okr: ExecutiveOkrSnapshot | null;
  /** Son veri girişi (ISO). null: tenant'ta hiç yorum yok. "Son 24
   *  saatte yükleme yok → yükleme alanı öne" kuralının kaynağı. */
  last_data_at: string | null;
}

export function useExecutiveOverview() {
  return useQuery<ExecutiveOverview>({
    queryKey: ["executive-overview"],
    queryFn: () =>
      apiRequest<ExecutiveOverview>("/tenants/me/executive/overview"),
    // Yönetici sayfası: 60s tazelik yeterli; sekme değiştirip
    // dönüşte gereksiz refetch olmasın (global refetchOnWindowFocus
    // zaten kapalı).
    staleTime: 60_000,
  });
}
