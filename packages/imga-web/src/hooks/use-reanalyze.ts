"use client";

// Yeniden analiz — mevcut yorumları güncel sınıflandırma kurallarıyla
// yeniden işler. Üç kapsam:
//
//   useReanalyzeBatchJob  — tek yüklemenin yorumları
//   useReanalyzeAllReviews — kurumun tüm yorumları
//   useReanalyzeReview     — tek bir yorum (/reviews/[id] aksiyonu)
//
// İlk ikisi normal bir batch işi kuyruklar; iş, Geçmiş Yüklemeler
// listesinde "yeniden-analiz: ..." dosya adıyla belirir. Bu yüzden
// başarıda batch-history + batch-active invalidate edilir (upload
// sayfası mount'ta batch-active üzerinden aktif işe yeniden bağlanır).
//
// Yetki: tenant_admin (backend aksi halde 403) — useReanalyzeReview
// istisna: analyst da yazabildiği için write rolüne açık, backend 409
// döner (insan düzeltmesi var / içerik boş) veya 403 (viewer).

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

/** Tek bir yorumu yeniden analiz eder (/reviews/[id] aksiyonu). Diğer
 *  iki kapsamın batch-history/batch-active invalidation'ına EK olarak
 *  bu satırın kendi detay + liste sorgularını da tazeler — üç sorgu da
 *  aynı review_id/queue'ya bakıyor olabilir. */
export function useReanalyzeReview() {
  const invalidateBatch = useInvalidateBatchQueries();
  const queryClient = useQueryClient();
  return useMutation<ReanalyzeResult, Error, string>({
    mutationFn: async (reviewId) =>
      apiRequest<ReanalyzeResult>(`/tenants/me/reviews/${reviewId}/reanalyze`, {
        method: "POST",
      }),
    onSuccess: (_data, reviewId) => {
      invalidateBatch();
      queryClient.invalidateQueries({ queryKey: ["review-detail", reviewId] });
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
  });
}
