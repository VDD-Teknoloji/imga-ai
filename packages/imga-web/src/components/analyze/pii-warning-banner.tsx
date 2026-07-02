"use client";

// Sprint 8.3.8 — PII consent banner for /analyze/upload Step 2.
//
// Shown when the smart_parser detected at least one PII column
// (currently customer_name; future: email, phone, address). User
// must check the consent box before the upload form's submit
// button enables. The flag is frontend-only this sprint — the
// backend doesn't yet record the consent — but capturing it in the
// UI surface starts the audit trail right.

import { ShieldAlert } from "lucide-react";

import { useTranslation } from "@/lib/i18n/use-translation";
import type { SmartPreviewResponse } from "@/lib/types";

interface Props {
  preview: SmartPreviewResponse;
  consented: boolean;
  onConsentChange: (next: boolean) => void;
}

export function PiiWarningBanner({ preview, consented, onConsentChange }: Props) {
  const { t } = useTranslation();
  if (preview.pii_warnings.length === 0) return null;

  const columns = preview.pii_warnings.map((w) => w.split(":").slice(1).join(":"));

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm">
      <div className="flex items-start gap-3">
        <ShieldAlert className="mt-0.5 size-5 shrink-0 text-amber-700" aria-hidden />
        <div className="flex-1 space-y-2">
          <p className="font-medium text-amber-900">
            {t("analyze.pii.heading")}
          </p>
          <p className="text-amber-900">
            {t("analyze.pii.detectedColumns")}
            {columns.map((c, idx) => (
              <span key={c} className="font-mono">
                {c}
                {idx < columns.length - 1 ? ", " : ""}
              </span>
            ))}
          </p>
          <p className="text-amber-800 text-xs">
            {t("analyze.pii.body")}
          </p>
          <label className="flex items-start gap-2 pt-1 font-medium text-amber-900">
            <input
              type="checkbox"
              checked={consented}
              onChange={(e) => onConsentChange(e.target.checked)}
              className="mt-0.5 size-4"
            />
            <span>
              {t("analyze.pii.consent")}
            </span>
          </label>
        </div>
      </div>
    </div>
  );
}
