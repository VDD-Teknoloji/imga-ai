"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, apiRequest } from "@/lib/api-client";
import type { AutomationMode, CategoryView } from "@/lib/types";

/**
 * Settings page reads the tenant config snapshot via this hook and
 * mutates pieces of it via the five mutations below. Every mutation
 * invalidates both ["tenant","config"] (the snapshot) and
 * ["tenant","categories"] (the slimmer list used by the dashboard
 * label-map and the ticket-list filters), so a label edit ripples
 * everywhere.
 */

export interface TenantConfigResponse {
  tenant_id: string;
  automation_mode: AutomationMode;
  categories: CategoryView[];
}

const CONFIG_KEY = ["tenant", "config"] as const;
const CATEGORIES_KEY = ["tenant", "categories"] as const;

async function fetchTenantConfig(): Promise<TenantConfigResponse> {
  return apiRequest<TenantConfigResponse>("/tenants/me/config");
}

export function useTenantConfig() {
  return useQuery({ queryKey: CONFIG_KEY, queryFn: fetchTenantConfig });
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>): void {
  qc.invalidateQueries({ queryKey: CONFIG_KEY });
  qc.invalidateQueries({ queryKey: CATEGORIES_KEY });
}

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "Bu işlem için yetkin yok.";
    if (err.status === 404) return "Kayıt bulunamadı.";
    if (err.status === 409) return err.detail || "Kod zaten kullanımda.";
    if (err.status === 422) return "Eksik veya geçersiz alan.";
  }
  return fallback;
}

// --- mutations ---------------------------------------------------------

export function useUpdateAutomationMode() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { mode: AutomationMode }>({
    mutationFn: async ({ mode }) => {
      await apiRequest<void>("/tenants/me/automation-mode", {
        method: "PATCH",
        body: { automation_mode: mode },
      });
    },
    onSuccess: () => {
      toast.success("Otomasyon modu güncellendi");
      invalidateAll(qc);
    },
    onError: (err) => {
      toast.error(describeError(err, "Otomasyon modu güncellenemedi."));
    },
  });
}

export function useToggleCategory() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { categoryId: string; isEnabled: boolean }>({
    mutationFn: async ({ categoryId, isEnabled }) => {
      await apiRequest<void>(`/tenants/me/categories/${categoryId}`, {
        method: "PATCH",
        body: { is_enabled: isEnabled },
      });
    },
    // No per-call toast — the toggle list batches multiple PATCHes
    // behind a single "Kaydet" so the page surfaces one summary
    // toast (handled in the component).
    onSettled: () => {
      invalidateAll(qc);
    },
  });
}

interface CustomCategoryInput {
  code: string;
  label_tr: string;
  label_en?: string | null;
  description?: string | null;
}

export function useCreateCustomCategory() {
  const qc = useQueryClient();
  return useMutation<CategoryView, ApiError, CustomCategoryInput>({
    mutationFn: async (body) => {
      const payload: Record<string, unknown> = {
        code: body.code,
        label_tr: body.label_tr,
      };
      if (body.label_en) payload.label_en = body.label_en;
      if (body.description) payload.description = body.description;
      return apiRequest<CategoryView>("/tenants/me/custom-categories", {
        method: "POST",
        body: payload,
      });
    },
    onSuccess: () => {
      toast.success("Kategori oluşturuldu");
      invalidateAll(qc);
    },
    onError: (err) => {
      toast.error(describeError(err, "Kategori oluşturulamadı."));
    },
  });
}

interface UpdateCustomInput {
  categoryId: string;
  label_tr?: string;
  label_en?: string | null;
  description?: string | null;
}

export function useUpdateCustomCategory() {
  const qc = useQueryClient();
  return useMutation<CategoryView, ApiError, UpdateCustomInput>({
    mutationFn: async ({ categoryId, ...body }) => {
      const payload: Record<string, unknown> = {};
      if (body.label_tr !== undefined) payload.label_tr = body.label_tr;
      if (body.label_en !== undefined) payload.label_en = body.label_en;
      if (body.description !== undefined) payload.description = body.description;
      return apiRequest<CategoryView>(`/tenants/me/custom-categories/${categoryId}`, {
        method: "PATCH",
        body: payload,
      });
    },
    onSuccess: () => {
      toast.success("Kategori güncellendi");
      invalidateAll(qc);
    },
    onError: (err) => {
      toast.error(describeError(err, "Kategori güncellenemedi."));
    },
  });
}

export function useArchiveCustomCategory() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { categoryId: string }>({
    mutationFn: async ({ categoryId }) => {
      await apiRequest<void>(`/tenants/me/custom-categories/${categoryId}`, {
        method: "DELETE",
      });
    },
    onSuccess: () => {
      toast.success("Kategori arşivlendi");
      invalidateAll(qc);
    },
    onError: (err) => {
      toast.error(describeError(err, "Kategori arşivlenemedi."));
    },
  });
}
