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
  /** F2 (2026-09-02) — arka planda başka bir ajan tarafından eklenen alan
   *  (root-cause.ts prompt genişlemesi): serbest metin uzman yorumu. Eski
   *  kalıcı analizlerde yok — opsiyonel, `generating?` ile aynı savunma. */
  expert_note?: string | null;
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
  /** home-liveliness (2026-09-02) — paralel bir backend ajanı ekliyor:
   *  share_pct'in gerçek paydası (bu pencerede TÜM negatifler, 'belirsiz'
   *  dahil — root_cause_service.py total_negative_count). Eskiden karta
   *  hiç yansımayan bu sayı, hero'nun tüm-zamanlar negatif sayısıyla
   *  karıştırılan "%67" şikayetinin kök nedeniydi (bkz. görev notu).
   *  `generating?`/`last_error?` ile aynı gerekçeyle opsiyonel: web + api
   *  bağımsız deploy edilir, eski sunucu bu alanları hiç göndermeyebilir. */
  window_negative_total?: number;
  /** YYYY-MM-DD, backend `date` tipiyle aynı ham biçim (bu dosyanın
   *  üstündeki date_from/date_to notuyla aynı — ISO'ya genişletilmez). */
  window_from?: string | null;
  window_to?: string | null;
  /** Bugün tek değer taşır: "window_negatives_all" — ileride başka bir
   *  payda tanımı eklenirse FE bunu ayırt edebilsin diye string (enum
   *  değil) bırakıldı. */
  share_basis?: string;
}

export interface RootCauseOverviewResponse {
  cards: RootCauseOverviewCard[];
  /** Arka planda kuyruklanmış üretim sürerken true — backend tarafı bu
   *  sprintte ayrı bir ajan tarafından ekleniyor, o yüzden opsiyonel:
   *  alan henüz gelmeyen eski/yeni sunucu karışımında da derlenir. */
  generating?: boolean;
  /** F2 (2026-09-02) — en son otomatik üretim denemesinin sonucu; kart
   *  hiç üretilmemişse (cards boş) boş-durum kopyası bu alana göre
   *  seçilir (root-cause-cards.tsx). `generating?` ile aynı gerekçeyle
   *  opsiyonel. */
  last_error?: "no_credentials" | "failed" | null;
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
      apiRequest<RootCauseOverviewResponse>(`/tenants/me/insights/root-cause/overview?${query}`),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    // generating true iken 5sn'de bir yoklar — arka plan üretimi bitince
    // (generating false) durur (use-reports.ts'teki useReportJob ile aynı
    // idiom: query.state.data üzerinden karar, ayrı bir state yok).
    refetchInterval: (query) => (query.state.data?.generating ? 5000 : false),
  });
}
