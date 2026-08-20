// 2026-08-20 — /reviews boyut filtre dropdown'ları için değer listesi.
// Backend count desc sıralı döner (≤100 satır). staleTime uzun tutuldu:
// bu liste yalnız yeni bir CSV yüklemesi / CRM güncellemesiyle değişir,
// her filtre dropdown açılışında yeniden çekilmesi gereksiz.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export type DimensionValueField =
  | "channel"
  | "business_segment"
  | "product_line"
  | "customer_tier"
  | "entered_by"
  | "source";

export interface DimensionValueRow {
  value: string;
  count: number;
}

export interface DimensionValuesResponse {
  values: DimensionValueRow[];
}

/** ``includeFlagged`` varsayılan true — bu uç filtre dropdown'larının
 *  evrenini besliyor; düşük kaliteli satırlarda geçen bir değeri
 *  (örn. yalnız bayraklı satırlarda görülen bir "channel") dropdown'dan
 *  gizlemek analisti şaşırtır. Sayfanın kendi include_flagged
 *  filtresinden bağımsız — dropdown seçenek evreni her zaman en geniş
 *  küme, filtrelemenin kendisi ayrı bir işlem. */
export function useDimensionValues(field: DimensionValueField, includeFlagged = true) {
  return useQuery<DimensionValuesResponse>({
    queryKey: ["dimension-values", field, includeFlagged],
    queryFn: () =>
      apiRequest<DimensionValuesResponse>(
        `/tenants/me/reviews/dimension-values?field=${field}&include_flagged=${includeFlagged}`,
      ),
    staleTime: 5 * 60 * 1000,
  });
}
