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

import { ApiError } from "@/lib/api-client";
import type { SmartPreviewResponse } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

/** Upload a file to the preview endpoint. We bypass the JSON
 *  ``apiRequest`` wrapper because the body is multipart — same
 *  pattern as the existing batch upload mutation. */
async function previewBatchColumns(file: File): Promise<SmartPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  // Auth rides on the HttpOnly session cookie — credentials:include is
  // required for cross-origin (web :3000 → api :8003) cookie delivery.
  const res = await fetch(`${API_BASE}/tenants/me/analyze/batch/preview`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep the default detail string.
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as SmartPreviewResponse;
}

export function useSmartPreview() {
  return useMutation<SmartPreviewResponse, Error, File>({
    mutationFn: (file) => previewBatchColumns(file),
  });
}
