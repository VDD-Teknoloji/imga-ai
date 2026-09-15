"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRawFetch, apiRequest } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import type { DocumentSnapshot } from "@/lib/intelligence-types";

export const INTELLIGENCE_API = "/tenants/me/intelligence";
export function useIntelligenceTenant() {
  return useAuthStore((state) => state.activeContext?.tenant_id ?? "");
}
export function useIntelligenceQuery<T>(path: string, enabled = true) {
  const tenant = useIntelligenceTenant();
  return useQuery<T>({
    queryKey: ["intelligence", tenant, path],
    enabled: !!tenant && enabled,
    queryFn: ({ signal }) => apiRequest<T>(INTELLIGENCE_API + path, { signal }),
    refetchOnWindowFocus: false,
  });
}
export function useSaveDocument<T>(kind: "prd" | "company") {
  const tenant = useIntelligenceTenant();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { expected_revision: number; status: "draft" | "approved"; content: T }) =>
      apiRequest<DocumentSnapshot<T>>(`${INTELLIGENCE_API}/documents/${kind}`, {
        method: "PUT",
        body,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["intelligence", tenant] });
    },
  });
}
export function useIntelligenceUrl() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = useState(() => params.toString());
  useEffect(() => {
    // URL navigation mirrors local state (mandatory Path B pattern).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQuery((previous) => (previous === params.toString() ? previous : params.toString()));
  }, [params]);
  function change(values: Record<string, string>, replace = false) {
    const next = new URLSearchParams(query);
    Object.entries(values).forEach(([key, value]) =>
      value ? next.set(key, value) : next.delete(key),
    );
    setQuery(next.toString());
    const url = next.size ? `${pathname}?${next}` : pathname;
    if (replace) router.replace(url, { scroll: false });
    else router.push(url, { scroll: false });
  }
  return { params: new URLSearchParams(query), change };
}
export async function downloadIntelligence(path: string, filename: string) {
  const response = await apiRawFetch(INTELLIGENCE_API + path);
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
