// Sprint 8.3.8 — column detection preview for /analyze/upload Step 2.
//
// Single mutation hook that uploads the picked file to /tenants/me/
// analyze/batch/preview, runs the SmartColumnDetector ensemble on the
// first ~50 rows, and returns the per-column suggestions + PII
// warnings. The actual upload still goes through useBatchUploadMutation
// (existing); this preview is purely informational so the user can
// confirm or override the auto-detected ``text_column`` before
// committing.

import { useMutation } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { SmartPreviewResponse } from "@/lib/types";

// Sprint 13 (HATA-04) — raw fetch yerine apiRequest: wrapper FormData'yı
// zaten destekliyor ve 401'de tryRefresh+tek replay yapıyor. Eski raw
// fetch, access cookie 15 dk'da düşünce "missing access token" toast'ı
// üretiyordu (refresh cookie canlıyken bile).
async function previewBatchColumns(file: File): Promise<SmartPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  return apiRequest<SmartPreviewResponse>(
    "/tenants/me/analyze/batch/preview",
    { method: "POST", body: form },
  );
}

export function useSmartPreview() {
  return useMutation<SmartPreviewResponse, Error, File>({
    mutationFn: (file) => previewBatchColumns(file),
  });
}
