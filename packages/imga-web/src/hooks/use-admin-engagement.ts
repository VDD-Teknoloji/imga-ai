// Katılım eşikleri — süper yönetici tarafı.
//
// Eşiklerin "iyi/kötü" yargısı sektöre bağlı olduğu için kurum
// düzenlemez; bu uçlar yalnızca süper yöneticiye açıktır.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { EngagementBand } from "@/hooks/use-engagement";

export interface AdminEngagementBands {
  tenant_id: string;
  bands: EngagementBand[];
  is_default: boolean;
}

const ADMIN_BANDS_KEY = ["admin-engagement-bands"] as const;

export function useAdminEngagementBands(tenantId: string | undefined) {
  return useQuery<AdminEngagementBands>({
    queryKey: [...ADMIN_BANDS_KEY, tenantId],
    enabled: typeof tenantId === "string",
    queryFn: () => apiRequest<AdminEngagementBands>(`/admin/tenants/${tenantId}/engagement-bands`),
  });
}

export function useUpdateAdminEngagementBands() {
  const qc = useQueryClient();
  return useMutation<AdminEngagementBands, Error, { tenantId: string; bands: EngagementBand[] }>({
    mutationFn: ({ tenantId, bands }) =>
      apiRequest<AdminEngagementBands>(`/admin/tenants/${tenantId}/engagement-bands`, {
        method: "PUT",
        body: { bands },
      }),
    // PUT yanıtı GET ile aynı şekli döner; cache'i doğrudan yazıyoruz.
    // Yalnız invalidate edilseydi dialog kapanıp yeniden açıldığında
    // react-query önce bayat GET'i servis eder, form taslağı ilk düşen
    // veriyle bir kez tohumlandığı için kaydedilen değerler geri
    // görünürdü — sonraki Kaydet kullanıcının kendi değişikliğini geri alır.
    onSuccess: (data, variables) => {
      qc.setQueryData([...ADMIN_BANDS_KEY, variables.tenantId], data);
      qc.invalidateQueries({
        queryKey: [...ADMIN_BANDS_KEY, variables.tenantId],
      });
    },
  });
}
