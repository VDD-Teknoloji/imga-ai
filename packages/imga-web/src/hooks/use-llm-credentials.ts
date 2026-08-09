// Kurum tarafı LLM kimlik okuma hook'ları.
//
// 2026-08-09: model + API anahtarı YÖNETİMİ süper yöneticiye taşındı
// (bkz. use-admin-llm-credentials.ts). Mutation hook'ları buradan
// kaldırıldı çünkü backend'de karşılık gelen uçlar da kaldırıldı —
// kurum tarafında yalnız iki okuma yolu kaldı:
//   * useLlmCredentials — liste (yalnız önizleme, asla düz metin)
//   * useOpenRouterModels — model kataloğu (salt okunur)
//
// useLlmCredentials aynı zamanda /strategy ve /executive-briefing
// sayfalarının "kimlik tanımlı mı" CTA kapısını besler; yanıt şekli
// bilinçli olarak değişmedi.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  LlmCredential,
  OpenRouterModelListResponse,
} from "@/lib/types";

const QUERY_KEY = ["llm-credentials"] as const;

/** OpenRouter canlı model kataloğu (backend 1 saat önbellekler; FE de
 *  aynı ufukta stale tutar). Model seçici açılmadan istek atılmasın
 *  diye ``enabled`` parametresiyle tembel. */
export function useOpenRouterModels(enabled: boolean) {
  return useQuery<OpenRouterModelListResponse>({
    queryKey: ["openrouter-models"],
    queryFn: () =>
      apiRequest<OpenRouterModelListResponse>(
        "/tenants/me/llm-credentials/openrouter-models",
      ),
    enabled,
    staleTime: 3600_000,
  });
}

export function useLlmCredentials() {
  return useQuery<LlmCredential[]>({
    queryKey: QUERY_KEY,
    queryFn: () => apiRequest<LlmCredential[]>("/tenants/me/llm-credentials"),
  });
}
