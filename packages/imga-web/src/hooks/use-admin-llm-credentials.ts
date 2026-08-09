"use client";

// 2026-08-09 — süper-yönetici LLM kimlik yönetimi.
//
// Model + API anahtarı yönetimi kurumdan alınıp IMGA'ya (süper
// yönetici) verildi. Bu dosya /admin/tenants/{id}/llm-credentials/*
// uçlarını sarar; kurum tarafındaki use-llm-credentials.ts artık
// yalnızca okuma yapar.
//
// Model kataloğu ayrı bir uçtan (/admin/openrouter-models) gelir:
// süper yöneticinin aktif kurumu olmadığı için kurum-tarafı katalog
// ucu onun bağlamında 400 döner.
//
// Güvenlik sözleşmesi değişmedi: düz metin anahtar yalnız create
// gövdesinde yolculuk eder; her yanıt sadece ``value_preview`` (son 4
// karakter) taşır.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  LlmCredential,
  LlmProviderName,
  OpenRouterModelListResponse,
} from "@/lib/types";

export interface AdminLlmCredentialCreateRequest {
  label: string;
  api_key: string;
  provider: LlmProviderName;
  /** OpenRouter model kimliği; null → sağlayıcı varsayılanı. */
  model?: string | null;
}

export interface AdminLlmCredentialUpdateRequest {
  label?: string;
  is_active?: boolean;
  /** Açık null → sağlayıcı varsayılanına dön. */
  model?: string | null;
}

export interface AdminLlmCredentialReorderRequest {
  ordered_ids: string[];
}

const ADMIN_LLM_KEY = "admin-llm-credentials";

function queryKey(tenantId: string) {
  return [ADMIN_LLM_KEY, tenantId] as const;
}

function basePath(tenantId: string) {
  return `/admin/tenants/${tenantId}/llm-credentials`;
}

/** Süper-yönetici model kataloğu. Seçici açılmadan istek atılmasın
 *  diye ``enabled`` ile tembel; backend 1 saat önbelleklediği için FE
 *  de aynı ufukta stale tutar. */
export function useAdminOpenRouterModels(enabled: boolean) {
  return useQuery<OpenRouterModelListResponse>({
    queryKey: ["admin-openrouter-models"],
    queryFn: () =>
      apiRequest<OpenRouterModelListResponse>("/admin/openrouter-models"),
    enabled,
    staleTime: 3600_000,
  });
}

export function useAdminLlmCredentials(tenantId: string) {
  return useQuery<LlmCredential[]>({
    queryKey: queryKey(tenantId),
    queryFn: () => apiRequest<LlmCredential[]>(basePath(tenantId)),
    enabled: tenantId.length > 0,
  });
}

export function useCreateAdminLlmCredential(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<LlmCredential, Error, AdminLlmCredentialCreateRequest>({
    mutationFn: (body) =>
      apiRequest<LlmCredential>(basePath(tenantId), {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKey(tenantId) });
    },
  });
}

export function useUpdateAdminLlmCredential(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<
    LlmCredential,
    Error,
    { id: string; body: AdminLlmCredentialUpdateRequest }
  >({
    mutationFn: ({ id, body }) =>
      apiRequest<LlmCredential>(`${basePath(tenantId)}/${id}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKey(tenantId) });
    },
  });
}

/** İyimser sıralama: sürükleme anında yerel sıra uygulanır, backend
 *  hata verirse ``onError`` önceki anlık görüntüye döner. TanStack
 *  Query önbelleği tek doğruluk kaynağı — sayfa paralel bir sürükleme
 *  state'i tutmaz. */
export function useReorderAdminLlmCredentials(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<
    LlmCredential[],
    Error,
    AdminLlmCredentialReorderRequest,
    { previous: LlmCredential[] | undefined }
  >({
    mutationFn: (body) =>
      apiRequest<LlmCredential[]>(`${basePath(tenantId)}/reorder`, {
        method: "PUT",
        body,
      }),
    onMutate: async ({ ordered_ids }) => {
      await qc.cancelQueries({ queryKey: queryKey(tenantId) });
      const previous = qc.getQueryData<LlmCredential[]>(queryKey(tenantId));
      if (previous) {
        const byId = new Map(previous.map((c) => [c.id, c]));
        const next = ordered_ids
          .map((id, index) => {
            const cred = byId.get(id);
            return cred ? { ...cred, priority: index } : null;
          })
          .filter((c): c is LlmCredential => c !== null);
        qc.setQueryData(queryKey(tenantId), next);
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        qc.setQueryData(queryKey(tenantId), context.previous);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKey(tenantId) });
    },
  });
}

export function useDeleteAdminLlmCredential(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) =>
      apiRequest<void>(`${basePath(tenantId)}/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKey(tenantId) });
    },
  });
}
