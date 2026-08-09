// Sprint 8.3.6.6 — tenant LLM credential CRUD + reorder.
//
// Five hooks against /tenants/me/llm-credentials/*:
//   * useLlmCredentials — list (preview only, never plaintext)
//   * useCreateLlmCredential — POST (plaintext goes here, never again)
//   * useUpdateLlmCredential — PATCH label / is_active
//   * useReorderLlmCredentials — PUT full ordered ID list (drag-reorder UI)
//   * useDeleteLlmCredential — DELETE
//
// Backend security contract: plaintext API key only travels in the
// create request body. Every list/update/reorder response carries
// only ``value_preview`` (last 4 chars). Hook layer doesn't need to
// hold the plaintext after submit — caller's form state should clear
// the field on success.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  LlmCredential,
  LlmCredentialCreateRequest,
  LlmCredentialReorderRequest,
  LlmCredentialUpdateRequest,
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

export function useCreateLlmCredential() {
  const qc = useQueryClient();
  return useMutation<LlmCredential, Error, LlmCredentialCreateRequest>({
    mutationFn: (body) =>
      apiRequest<LlmCredential>("/tenants/me/llm-credentials", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

export function useUpdateLlmCredential() {
  const qc = useQueryClient();
  return useMutation<
    LlmCredential,
    Error,
    { id: string; body: LlmCredentialUpdateRequest }
  >({
    mutationFn: ({ id, body }) =>
      apiRequest<LlmCredential>(`/tenants/me/llm-credentials/${id}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

/** Optimistic reorder: locally apply the new ordering immediately so
 *  the drag UX feels instant; on backend failure, the
 *  ``onError`` rollback restores the previous snapshot. The TanStack
 *  Query cache is the single source of truth — page components read
 *  the ordered list off ``useLlmCredentials`` and don't keep a parallel
 *  drag state. */
export function useReorderLlmCredentials() {
  const qc = useQueryClient();
  return useMutation<
    LlmCredential[],
    Error,
    LlmCredentialReorderRequest,
    { previous: LlmCredential[] | undefined }
  >({
    mutationFn: (body) =>
      apiRequest<LlmCredential[]>("/tenants/me/llm-credentials/reorder", {
        method: "PUT",
        body,
      }),
    onMutate: async ({ ordered_ids }) => {
      await qc.cancelQueries({ queryKey: QUERY_KEY });
      const previous = qc.getQueryData<LlmCredential[]>(QUERY_KEY);
      if (previous) {
        const byId = new Map(previous.map((c) => [c.id, c]));
        const next = ordered_ids
          .map((id, index) => {
            const cred = byId.get(id);
            return cred ? { ...cred, priority: index } : null;
          })
          .filter((c): c is LlmCredential => c !== null);
        qc.setQueryData(QUERY_KEY, next);
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        qc.setQueryData(QUERY_KEY, context.previous);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

export function useDeleteLlmCredential() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) =>
      apiRequest<void>(`/tenants/me/llm-credentials/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
