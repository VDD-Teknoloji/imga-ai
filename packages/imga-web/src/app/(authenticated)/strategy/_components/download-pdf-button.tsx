"use client";

// PDF indirme butonu — SWOT/OKR görüntüleyicileri VE Geçmiş sekmesi
// (page.tsx) paylaşıyor; tek yerde tutulur ki iki yerde aynı fetch+blob+
// anchor mantığı yeniden yazılmasın.

import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { apiRawFetch } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { StrategicReportType } from "@/lib/types";

async function downloadStrategicPdf(
  reportId: string,
  reportType: StrategicReportType,
  t: (key: string, vars?: Record<string, string | number>) => string,
): Promise<void> {
  // Same fetch+blob+anchor pattern as /reports — credentials:'include'
  // ships the auth cookie on this cross-origin XHR; a plain
  // <a download> can't. Sprint 13 (HATA-04) — apiRawFetch: 401'de
  // refresh+tek replay'den geçer.
  // Backend route is /download.pdf (per imga-api routes/strategic_
  // reports.py); the bare /pdf shape returned 404 in production.
  const path = `/tenants/me/strategic-reports/${reportId}/download.pdf`;
  try {
    const res = await apiRawFetch(path);
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      toast.error(
        t("dashboard.strategy.pdf.downloadFailed", {
          status: res.status,
          detail: detail.slice(0, 80),
        }),
      );
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download =
      res.headers.get("content-disposition")?.match(/filename="?([^"]+)"?/)?.[1] ??
      `imga-${reportType}-${reportId.slice(0, 8)}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch {
    toast.error(t("dashboard.strategy.pdf.downloadStartFailed"));
  }
}

export function DownloadPdfButton({
  reportId,
  reportType,
  size = "default",
  variant = "outline",
}: {
  reportId: string;
  reportType: StrategicReportType;
  size?: "default" | "sm";
  variant?: "default" | "outline" | "ghost";
}) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  return (
    <Button
      variant={variant}
      size={size}
      disabled={pending}
      onClick={async () => {
        setPending(true);
        try {
          await downloadStrategicPdf(reportId, reportType, t);
        } finally {
          setPending(false);
        }
      }}
      className="gap-1"
    >
      {pending ? (
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
      ) : (
        <Download className="size-3.5" aria-hidden />
      )}
      PDF
    </Button>
  );
}
