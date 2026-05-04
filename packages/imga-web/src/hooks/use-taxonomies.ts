// Sprint 8.3.5.6 — read-only taxonomy hook for /reviews + /insights.
// Sprint 8.3.7-A — full CRUD + reorder for /settings/taxonomies.
//
// One file, two consumers:
//   * useCompanyTaxonomies — backwards-compat read hook used by
//     /reviews (perspective filter) and /insights (label resolution).
//     Returns only the subset the consumers care about; cached
//     aggressively because that data rarely changes mid-session.
//   * useTaxonomies / useCreate... / useUpdate... / useDelete... /
//     useRestore... / useReorder... — the edit page surface.
//
// CategoryTaxonomyView (the older legacy type) and TaxonomyEntry (the
// 8.3.7 superset) coexist; CategoryTaxonomyView is structurally a
// subset, so an entry can be cast where a view is expected.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  CategoryTaxonomyView,
  TaxonomyCreateRequest,
  TaxonomyEntry,
  TaxonomyReorderRequest,
  TaxonomyUpdateRequest,
} from "@/lib/types";

const QUERY_KEY = ["taxonomies"] as const;

// --- Sprint 8.3.5.6 read-only consumers ----------------------------------

export function useCompanyTaxonomies() {
  return useQuery<CategoryTaxonomyView[]>({
    queryKey: ["company-taxonomies"],
    queryFn: () =>
      apiRequest<CategoryTaxonomyView[]>("/tenants/me/taxonomies"),
    staleTime: 5 * 60 * 1000,
  });
}

// --- Sprint 8.3.7-A edit surface -----------------------------------------

interface ListFilters {
  include_inactive?: boolean;
}

function listKey(filters: ListFilters): readonly unknown[] {
  return [...QUERY_KEY, { include_inactive: filters.include_inactive ?? false }];
}

export function useTaxonomies(filters: ListFilters = {}) {
  const include = filters.include_inactive ?? false;
  const qs = include ? "?include_inactive=true" : "";
  return useQuery<TaxonomyEntry[]>({
    queryKey: listKey(filters),
    queryFn: () => apiRequest<TaxonomyEntry[]>(`/tenants/me/taxonomies${qs}`),
  });
}

export function useCreateTaxonomy() {
  const qc = useQueryClient();
  return useMutation<TaxonomyEntry, Error, TaxonomyCreateRequest>({
    mutationFn: (body) =>
      apiRequest<TaxonomyEntry>("/tenants/me/taxonomies", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["company-taxonomies"] });
    },
  });
}

export function useUpdateTaxonomy() {
  const qc = useQueryClient();
  return useMutation<
    TaxonomyEntry,
    Error,
    { id: string; body: TaxonomyUpdateRequest }
  >({
    mutationFn: ({ id, body }) =>
      apiRequest<TaxonomyEntry>(`/tenants/me/taxonomies/${id}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["company-taxonomies"] });
    },
  });
}

export function useDeleteTaxonomy() {
  const qc = useQueryClient();
  return useMutation<TaxonomyEntry, Error, string>({
    mutationFn: (id) =>
      apiRequest<TaxonomyEntry>(`/tenants/me/taxonomies/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["company-taxonomies"] });
    },
  });
}

export function useRestoreTaxonomy() {
  const qc = useQueryClient();
  return useMutation<TaxonomyEntry, Error, string>({
    mutationFn: (id) =>
      apiRequest<TaxonomyEntry>(`/tenants/me/taxonomies/${id}/restore`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["company-taxonomies"] });
    },
  });
}

/** Optimistic drag-reorder — same pattern as use-llm-credentials. */
export function useReorderTaxonomies() {
  const qc = useQueryClient();
  return useMutation<
    TaxonomyEntry[],
    Error,
    TaxonomyReorderRequest,
    { previous: TaxonomyEntry[] | undefined; key: readonly unknown[] }
  >({
    mutationFn: (body) =>
      apiRequest<TaxonomyEntry[]>("/tenants/me/taxonomies/reorder", {
        method: "PUT",
        body,
      }),
    onMutate: async ({ ordered_ids }) => {
      // The drag UI lives on the active list (include_inactive=false);
      // optimistic update targets that key. The full-refetch on
      // onSettled invalidates ALL taxonomies queries to keep the
      // include_inactive=true variant honest too.
      const key = listKey({ include_inactive: false });
      await qc.cancelQueries({ queryKey: QUERY_KEY });
      const previous = qc.getQueryData<TaxonomyEntry[]>(key);
      if (previous) {
        const byId = new Map(previous.map((t) => [t.id, t]));
        const next = ordered_ids
          .map((id, index) => {
            const row = byId.get(id);
            return row ? { ...row, priority: index } : null;
          })
          .filter((t): t is TaxonomyEntry => t !== null);
        qc.setQueryData(key, next);
      }
      return { previous, key };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        qc.setQueryData(context.key, context.previous);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["company-taxonomies"] });
    },
  });
}
