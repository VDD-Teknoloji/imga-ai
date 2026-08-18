"use client";

// 2026-08-18 (Dalga 3, WS2) — toplu yükleme kalite raporu paneli.
//
// GET dialog açıldığında okunur — LLM'e dokunmaz. "Değerlendirme Üret"
// yalnız canWrite rollerine (tenant_admin/analyst) gösterilir — backend
// POST .../generate aynı matrisle korunuyor (_TenantMember); viewer'a
// buton hiç gösterilmez (403'e hiç varmaz). Bugün bu dialog yalnız
// "write" korumalı /analyze/upload/history sayfasından açılabiliyor,
// ama backend guard'ının frontend aynası kuralı gereği (bkz. require-
// role.tsx) viewer dalı yine de doğru davranışı taşır.

import { ClipboardList, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useGenerateQualityReport,
  useQualityReport,
} from "@/hooks/use-quality-report";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  jobId: string | null;
  open: boolean;
  onClose: () => void;
}

const SAMPLE_TEXT_MAX = 80;

function truncate(text: string, max = SAMPLE_TEXT_MAX): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function QualityReportDialog({ jobId, open, onClose }: Props) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  const { canWrite } = useRoleFlags();
  const report = useQualityReport(open ? jobId : null);
  const generate = useGenerateQualityReport();

  function onGenerate() {
    if (!jobId) return;
    generate.mutate(jobId, {
      onError: (err) => {
        if (err instanceof ApiError && err.detail) {
          toast.error(err.detail);
          return;
        }
        toast.error(t("analyze.history.qualityReport.generateFailed"));
      },
    });
  }

  const data = report.data;

  return (
    <Dialog open={open} onOpenChange={(v) => (v ? null : onClose())}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ClipboardList className="size-5" aria-hidden />
            {t("analyze.history.qualityReport.title")}
          </DialogTitle>
          <DialogDescription>
            {t("analyze.history.qualityReport.subtitle")}
          </DialogDescription>
        </DialogHeader>

        {report.isLoading ? (
          <div className="space-y-3 py-2">
            <Skeleton className="h-20 w-full rounded-2xl" />
            <Skeleton className="h-32 w-full rounded-2xl" />
          </div>
        ) : report.isError ? (
          <p className="text-destructive text-sm">
            {t("analyze.history.qualityReport.loadFailed")}
          </p>
        ) : data ? (
          <div className="space-y-5">
            {/* bayrak sayaçları */}
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <QualityStat
                label={t("analyze.history.qualityReport.duplicate")}
                value={data.counts.duplicate}
              />
              <QualityStat
                label={t("analyze.history.qualityReport.empty")}
                value={data.counts.empty}
              />
              <QualityStat
                label={t("analyze.history.qualityReport.informational")}
                value={data.counts.informational}
              />
              <QualityStat
                label={t("analyze.history.qualityReport.meaningless")}
                value={data.counts.meaningless}
              />
            </dl>

            {/* en çok tekrarlanan metinler */}
            {data.top_repeated_texts.length > 0 && (
              <div>
                <h4 className="mb-2 text-sm font-semibold">
                  {t("analyze.history.qualityReport.topRepeatedTitle")}
                </h4>
                <div className="overflow-x-auto rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("analyze.history.qualityReport.col.text")}</TableHead>
                        <TableHead className="text-right">
                          {t("analyze.history.qualityReport.col.count")}
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.top_repeated_texts.map((row) => (
                        <TableRow key={row.text_hash}>
                          <TableCell
                            className="max-w-xs truncate text-xs"
                            title={row.sample_text}
                          >
                            {truncate(row.sample_text)}
                          </TableCell>
                          <TableCell className="text-right text-xs tabular-nums">
                            {row.count.toLocaleString(numberLocale)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}

            {/* çalışan bazlı kırılım — boşsa bölüm hiç render edilmez */}
            {data.entered_by_breakdown.length > 0 && (
              <div>
                <h4 className="mb-2 text-sm font-semibold">
                  {t("analyze.history.qualityReport.byEmployeeTitle")}
                </h4>
                <div className="overflow-x-auto rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("analyze.history.qualityReport.col.employee")}</TableHead>
                        <TableHead className="text-right">
                          {t("analyze.history.qualityReport.col.total")}
                        </TableHead>
                        <TableHead className="text-right">
                          {t("analyze.history.qualityReport.duplicate")}
                        </TableHead>
                        <TableHead className="text-right">
                          {t("analyze.history.qualityReport.empty")}
                        </TableHead>
                        <TableHead className="text-right">
                          {t("analyze.history.qualityReport.informational")}
                        </TableHead>
                        <TableHead className="text-right">
                          {t("analyze.history.qualityReport.meaningless")}
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.entered_by_breakdown.map((row) => (
                        <TableRow key={row.entered_by ?? "__none__"}>
                          <TableCell className="text-xs">
                            {row.entered_by ?? t("analyze.history.qualityReport.unknownEmployee")}
                          </TableCell>
                          <TableCell className="text-right text-xs tabular-nums">
                            {row.total.toLocaleString(numberLocale)}
                          </TableCell>
                          <TableCell className="text-right text-xs tabular-nums">
                            {row.duplicate.toLocaleString(numberLocale)}
                          </TableCell>
                          <TableCell className="text-right text-xs tabular-nums">
                            {row.empty.toLocaleString(numberLocale)}
                          </TableCell>
                          <TableCell className="text-right text-xs tabular-nums">
                            {row.informational.toLocaleString(numberLocale)}
                          </TableCell>
                          <TableCell className="text-right text-xs tabular-nums">
                            {row.meaningless.toLocaleString(numberLocale)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}

            {/* yapay zekâ değerlendirmesi */}
            <div className="bg-muted/40 rounded-2xl border p-4">
              <div className="mb-2 flex items-center gap-2">
                <Sparkles className="text-primary size-4" aria-hidden />
                <h4 className="text-sm font-semibold">
                  {t("analyze.history.qualityReport.aiAssessmentTitle")}
                </h4>
              </div>
              {generate.isPending ? (
                <div className="text-muted-foreground flex items-center gap-2 text-sm">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  {t("analyze.history.qualityReport.generating")}
                </div>
              ) : data.summary ? (
                <div className="space-y-2">
                  <p className="text-sm leading-relaxed">{data.summary.assessment}</p>
                  <p className="text-muted-foreground text-xs">
                    {t("analyze.history.qualityReport.generatedMeta", {
                      model: data.summary.model_name,
                      date: new Date(data.summary.generated_at).toLocaleString(numberLocale),
                    })}
                  </p>
                </div>
              ) : canWrite ? (
                <div className="space-y-2">
                  <p className="text-muted-foreground text-sm">
                    {t("analyze.history.qualityReport.notGeneratedYet")}
                  </p>
                  <Button size="sm" onClick={onGenerate} disabled={generate.isPending} className="gap-2">
                    {t("analyze.history.qualityReport.generateButton")}
                  </Button>
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  {t("analyze.history.qualityReport.notGeneratedYetViewer")}
                </p>
              )}
            </div>
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("analyze.history.qualityReport.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function QualityStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-muted/30 rounded-md border p-3">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value.toLocaleString("tr-TR")}</dd>
    </div>
  );
}
