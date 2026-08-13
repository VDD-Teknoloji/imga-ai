"use client";

// Yeniden analiz — mevcut yorumları güncel sınıflandırma kurallarıyla
// yeniden işler. İki kapsam:
//
//   useReanalyzeBatchJob  — tek yüklemenin yorumları
//   useReanalyzeAllReviews — kurumun tüm yorumları
//
// İkisi de normal bir batch işi kuyruklar; iş, Geçmiş Yüklemeler
// listesinde "yeniden-analiz: ..." dosya adıyla belirir. Bu yüzden
// başarıda batch-history + batch-active invalidate edilir (upload
// sayfası mount'ta batch-active üzerinden aktif işe yeniden bağlanır).
//
// Yetki: tenant_admin (backend aksi halde 403).

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

/** Kuyruklanan işin kimliği. Gövdenin geri kalanı BatchJob alanlarıdır;
 *  UI yalnız job_id'ye dokunuyor, fazlasını tiplemiyoruz. */
export interface ReanalyzeResult {
  job_id: string;
}

function useInvalidateBatchQueries() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ["batch-history"] });
    queryClient.invalidateQueries({ queryKey: ["batch-active"] });
  };
}

/** Tek yüklemenin yorumlarını yeniden analiz eder. */
export function useReanalyzeBatchJob() {
  const invalidate = useInvalidateBatchQueries();
  return useMutation<ReanalyzeResult, Error, string>({
    mutationFn: async (jobId) =>
      apiRequest<ReanalyzeResult>(
        `/tenants/me/analyze/batch/${jobId}/reanalyze`,
        { method: "POST" },
      ),
    onSuccess: invalidate,
  });
}

/** Kurumun tüm yorumlarını yeniden analiz eder. */
export function useReanalyzeAllReviews() {
  const invalidate = useInvalidateBatchQueries();
  return useMutation<ReanalyzeResult, Error, void>({
    mutationFn: async () =>
      apiRequest<ReanalyzeResult>("/tenants/me/reviews/reanalyze-all", {
        method: "POST",
      }),
    onSuccess: invalidate,
  });
}
