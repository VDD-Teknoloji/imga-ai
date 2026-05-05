"use client";

// Sprint 8.3.6.6 — /strategy.
//
// Tek sayfa, üç tab: SWOT üret / OKR üret / Geçmiş. URL state Path B
// (?tab=swot|okr|history, ?date_from, ?date_to, ?report_id,
// ?source_report_id) — Suspense + mirror + URL→state useEffect, aynı
// /reviews ve /insights pattern'i.
//
// Disabled CTA: kullanıcının aktif (is_active=true) bir Gemini anahtarı
// yoksa "Üret" butonları kapalı; üstteki banner kullanıcıyı
// /settings/integrations sayfasına yönlendirir. Bu, ilk kullanımda
// 503 round-trip'inden ve şifreli hata mesajlarından kaçınmak için.
//
// PDF indirme: api-client JSON-only, Bearer header gerek; reports/page'in
// fetch+blob+anchor pattern'ini yeniden kullan.

import {
  AlertTriangle,
  ArrowRight,
  Compass,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
  Target,
  Wand2,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useExtractFromReport } from "@/hooks/use-action-items";
import { useLlmCredentials } from "@/hooks/use-llm-credentials";
import {
  useGenerateOkr,
  useGenerateSwot,
  useStrategicReport,
  useStrategicReports,
} from "@/hooks/use-strategic-reports";
import { ApiError } from "@/lib/api-client";
import { tokenStorage } from "@/lib/token-storage";
import type {
  OkrPayload,
  StrategicReportDetail,
  StrategicReportSummary,
  StrategicReportType,
  SwotPayload,
  SwotRecommendation,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

type TabKey = "swot" | "okr" | "history";

const TAB_LABELS: Record<TabKey, string> = {
  swot: "SWOT Üret",
  okr: "OKR Üret",
  history: "Geçmiş",
};

export default function StrategyPage() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <StrategyContent />
    </Suspense>
  );
}

function HeaderSkeleton() {
  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 p-6 md:p-8">
      <header className="flex items-center gap-2">
        <Compass className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">Strateji</h1>
          <p className="text-muted-foreground text-sm">Yükleniyor…</p>
        </div>
      </header>
    </main>
  );
}

function StrategyContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // URL → state mirror (Sprint 8.3.4 round-2 / 8.3.5.6 round-2 pattern).
  // useSearchParams stops notifying inside Suspense after the first
  // hydration; controlled primitives need a local state copy plus a
  // sync effect for back/forward navigation.
  const [tab, setTabState] = useState<TabKey>(
    () => (searchParams.get("tab") as TabKey) || "swot",
  );
  const [dateFrom, setDateFromState] = useState<string>(
    () => searchParams.get("date_from") ?? "",
  );
  const [dateTo, setDateToState] = useState<string>(
    () => searchParams.get("date_to") ?? "",
  );
  const [reportId, setReportIdState] = useState<string>(
    () => searchParams.get("report_id") ?? "",
  );
  const [sourceReportId, setSourceReportIdState] = useState<string>(
    () => searchParams.get("source_report_id") ?? "",
  );
  const [historyType, setHistoryTypeState] = useState<string>(
    () => searchParams.get("report_type") ?? "",
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlTab = (searchParams.get("tab") as TabKey) || "swot";
    setTabState((prev) => (prev === urlTab ? prev : urlTab));
    const urlFrom = searchParams.get("date_from") ?? "";
    setDateFromState((prev) => (prev === urlFrom ? prev : urlFrom));
    const urlTo = searchParams.get("date_to") ?? "";
    setDateToState((prev) => (prev === urlTo ? prev : urlTo));
    const urlReportId = searchParams.get("report_id") ?? "";
    setReportIdState((prev) => (prev === urlReportId ? prev : urlReportId));
    const urlSrc = searchParams.get("source_report_id") ?? "";
    setSourceReportIdState((prev) => (prev === urlSrc ? prev : urlSrc));
    const urlType = searchParams.get("report_type") ?? "";
    setHistoryTypeState((prev) => (prev === urlType ? prev : urlType));
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParam(updates: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") params.delete(key);
      else params.set(key, value);
    }
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  function handleTabChange(next: TabKey) {
    setTabState(next);
    // Clearing report_id / source_report_id when leaving a tab keeps
    // the URL semantically tab-scoped — otherwise a SWOT viewer's
    // ?report_id would persist into the OKR tab and confuse the page.
    if (next !== "swot") setReportIdState("");
    if (next !== "okr") setSourceReportIdState("");
    pushParam({
      tab: next,
      ...(next !== "swot" && { report_id: null }),
      ...(next !== "okr" && { source_report_id: null }),
    });
  }

  // Disabled-CTA gate. The /llm-credentials response is a flat list of
  // active+inactive rows; we only require at least one is_active. If the
  // list errors we still show the gate (assume blocked) — better a false
  // negative than an unguarded 503.
  const credentials = useLlmCredentials();
  const hasActiveKey = useMemo(
    () => (credentials.data ?? []).some((c) => c.is_active),
    [credentials.data],
  );
  const credentialsLoaded = !credentials.isLoading;

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 p-6 md:p-8">
      <header className="flex items-center gap-2">
        <Compass className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            Strateji
          </h1>
          <p className="text-muted-foreground text-sm">
            Analizleriniz üzerine SWOT ve OKR raporları üretin. Raporlar
            Gemini ile oluşturulur ve PDF olarak indirilebilir.
          </p>
        </div>
      </header>

      {credentialsLoaded && !hasActiveKey && (
        <NoCredentialBanner onNavigate={() => router.push("/settings/integrations")} />
      )}

      <Tabs value={tab} onValueChange={(v) => handleTabChange(v as TabKey)}>
        <TabsList className="grid w-full grid-cols-3 sm:w-fit">
          {(Object.keys(TAB_LABELS) as TabKey[]).map((k) => (
            <TabsTrigger key={k} value={k}>
              {TAB_LABELS[k]}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="swot" className="space-y-4">
          <SwotTab
            dateFrom={dateFrom}
            dateTo={dateTo}
            reportId={reportId}
            hasActiveKey={hasActiveKey}
            credentialsLoaded={credentialsLoaded}
            onDateFromChange={(v) => {
              setDateFromState(v);
              pushParam({ date_from: v || null });
            }}
            onDateToChange={(v) => {
              setDateToState(v);
              pushParam({ date_to: v || null });
            }}
            onSelectReport={(id) => {
              setReportIdState(id);
              pushParam({ report_id: id || null });
            }}
          />
        </TabsContent>

        <TabsContent value="okr" className="space-y-4">
          <OkrTab
            sourceReportId={sourceReportId}
            reportId={reportId}
            hasActiveKey={hasActiveKey}
            credentialsLoaded={credentialsLoaded}
            onSourceReportChange={(id) => {
              setSourceReportIdState(id);
              pushParam({ source_report_id: id || null });
            }}
            onSelectReport={(id) => {
              setReportIdState(id);
              pushParam({ report_id: id || null });
            }}
          />
        </TabsContent>

        <TabsContent value="history" className="space-y-4">
          <HistoryTab
            reportType={historyType}
            onReportTypeChange={(v) => {
              setHistoryTypeState(v);
              pushParam({ report_type: v || null });
            }}
            onOpenReport={(id, type) => {
              const targetTab: TabKey = type === "swot" ? "swot" : "okr";
              setTabState(targetTab);
              setReportIdState(id);
              pushParam({ tab: targetTab, report_id: id });
            }}
          />
        </TabsContent>
      </Tabs>
    </main>
  );
}

// --- Disabled-CTA banner ---------------------------------------------

function NoCredentialBanner({ onNavigate }: { onNavigate: () => void }) {
  return (
    <div className="bg-amber-50 flex flex-col gap-3 rounded-lg border border-amber-300 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 text-amber-600" aria-hidden />
        <div className="text-sm">
          <p className="font-medium text-amber-900">
            Strateji raporu üretmek için Gemini API anahtarı gerekli.
          </p>
          <p className="text-amber-800">
            En az bir aktif anahtar tanımlanana kadar SWOT/OKR üretimi devre
            dışı. Geçmiş raporlar görüntülenebilir ve indirilebilir.
          </p>
        </div>
      </div>
      <Button onClick={onNavigate} variant="outline" className="shrink-0 gap-2">
        Anahtar ekle <ArrowRight className="size-4" aria-hidden />
      </Button>
    </div>
  );
}

// --- SWOT tab --------------------------------------------------------

function SwotTab({
  dateFrom,
  dateTo,
  reportId,
  hasActiveKey,
  credentialsLoaded,
  onDateFromChange,
  onDateToChange,
  onSelectReport,
}: {
  dateFrom: string;
  dateTo: string;
  reportId: string;
  hasActiveKey: boolean;
  credentialsLoaded: boolean;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  onSelectReport: (id: string) => void;
}) {
  const generate = useGenerateSwot();
  const detail = useStrategicReport(reportId || null);
  const [forceRefresh, setForceRefresh] = useState(false);

  const generateDisabled =
    generate.isPending || !credentialsLoaded || !hasActiveKey;

  function onGenerate() {
    generate.mutate(
      {
        date_from: dateFrom || null,
        date_to: dateTo || null,
        force_refresh: forceRefresh,
      },
      {
        onSuccess: (report) => {
          onSelectReport(report.id);
          toast.success("SWOT raporu hazır.");
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.status === 503) {
              toast.error("Gemini şu an erişilemiyor: " + err.detail);
              return;
            }
            if (err.status === 400 || err.status === 422) {
              toast.error(err.detail);
              return;
            }
          }
          toast.error("SWOT raporu üretilemedi.");
        },
      },
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">SWOT raporu üret</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">
            Seçilen tarih aralığındaki analizler özetlenir, Gemini SWOT
            (güçlü/zayıf yönler, fırsat/tehdit) ve stratejik öneri çıktısı
            üretir. Tarih boş bırakılırsa son 90 gün kullanılır.
          </p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <Label className="text-xs">Başlangıç</Label>
              <input
                type="date"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={(e) => onDateFromChange(e.target.value)}
                className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
              />
            </div>
            <div>
              <Label className="text-xs">Bitiş</Label>
              <input
                type="date"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={(e) => onDateToChange(e.target.value)}
                className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={forceRefresh}
                  onChange={(e) => setForceRefresh(e.target.checked)}
                  className="size-4"
                />
                Önbelleği atla (yeniden üret)
              </label>
            </div>
          </div>
          <div>
            <Button
              onClick={onGenerate}
              disabled={generateDisabled}
              className="gap-2"
            >
              {generate.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Wand2 className="size-4" aria-hidden />
              )}
              SWOT üret
            </Button>
            {!hasActiveKey && credentialsLoaded && (
              <p className="text-muted-foreground mt-2 text-xs">
                Aktif Gemini anahtarı yok — yukarıdaki uyarıdan eklemeniz
                gerekir.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {reportId && detail.data && detail.data.report_type === "swot" && (
        <SwotViewer report={detail.data} />
      )}
      {reportId && detail.isLoading && (
        <Card>
          <CardContent className="flex items-center gap-2 p-6 text-sm">
            <Loader2 className="size-4 animate-spin" /> Rapor yükleniyor…
          </CardContent>
        </Card>
      )}
      {reportId && detail.isError && (
        <Card>
          <CardContent className="text-destructive p-6 text-sm">
            Rapor yüklenemedi.
          </CardContent>
        </Card>
      )}
    </>
  );
}

// --- SWOT viewer -----------------------------------------------------

const SWOT_PRIORITY_TONE: Record<string, string> = {
  yüksek: "bg-red-50 border-red-300 text-red-800",
  orta: "bg-amber-50 border-amber-300 text-amber-800",
  düşük: "bg-emerald-50 border-emerald-300 text-emerald-800",
};

const SWOT_QUADRANTS: ReadonlyArray<{
  key: keyof Pick<SwotPayload, "strengths" | "weaknesses" | "opportunities" | "threats">;
  label: string;
  tone: string;
}> = [
  { key: "strengths", label: "Güçlü Yönler", tone: "bg-emerald-50 border-emerald-300" },
  { key: "weaknesses", label: "Zayıf Yönler", tone: "bg-red-50 border-red-300" },
  { key: "opportunities", label: "Fırsatlar", tone: "bg-blue-50 border-blue-300" },
  { key: "threats", label: "Tehditler", tone: "bg-orange-50 border-orange-300" },
];

function SwotViewer({ report }: { report: StrategicReportDetail }) {
  const payload = report.output_payload as unknown as SwotPayload;
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="text-base">SWOT Raporu</CardTitle>
          <p className="text-muted-foreground mt-1 text-xs">
            <ReportMeta report={report} />
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ExtractActionItemsButton reportId={report.id} />
          <DownloadPdfButton reportId={report.id} reportType="swot" />
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {SWOT_QUADRANTS.map((q) => (
            <div key={q.key} className={`rounded-lg border p-4 ${q.tone}`}>
              <h3 className="mb-3 text-sm font-semibold">{q.label}</h3>
              <ul className="space-y-3">
                {payload[q.key].length === 0 ? (
                  <li className="text-muted-foreground text-xs">Madde yok.</li>
                ) : (
                  payload[q.key].map((item, idx) => (
                    <li key={idx} className="space-y-1 text-sm">
                      <p className="font-medium">{item.title}</p>
                      <p className="text-muted-foreground text-xs">
                        {item.description}
                      </p>
                      {item.evidence && (
                        <p className="text-muted-foreground text-xs italic">
                          Kanıt: {item.evidence}
                        </p>
                      )}
                    </li>
                  ))
                )}
              </ul>
            </div>
          ))}
        </div>

        {payload.strategic_recommendations.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">Stratejik Öneriler</h3>
            <ul className="space-y-2">
              {payload.strategic_recommendations.map((rec, idx) => (
                <RecommendationRow key={idx} rec={rec} />
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RecommendationRow({ rec }: { rec: SwotRecommendation }) {
  const priorityTone =
    SWOT_PRIORITY_TONE[rec.priority.toLowerCase()] ??
    "bg-gray-50 border-gray-300 text-gray-800";
  const impactTone =
    SWOT_PRIORITY_TONE[rec.estimated_impact.toLowerCase()] ??
    "bg-gray-50 border-gray-300 text-gray-800";
  return (
    <li className="bg-card space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium">{rec.title}</p>
        <Badge variant="outline" className={`text-xs ${priorityTone}`}>
          öncelik: {rec.priority}
        </Badge>
        <Badge variant="outline" className={`text-xs ${impactTone}`}>
          etki: {rec.estimated_impact}
        </Badge>
      </div>
      <p className="text-muted-foreground text-sm">{rec.description}</p>
    </li>
  );
}

// --- OKR tab ---------------------------------------------------------

function OkrTab({
  sourceReportId,
  reportId,
  hasActiveKey,
  credentialsLoaded,
  onSourceReportChange,
  onSelectReport,
}: {
  sourceReportId: string;
  reportId: string;
  hasActiveKey: boolean;
  credentialsLoaded: boolean;
  onSourceReportChange: (id: string) => void;
  onSelectReport: (id: string) => void;
}) {
  const swotList = useStrategicReports({ report_type: "swot", limit: 50 });
  const generate = useGenerateOkr();
  const detail = useStrategicReport(reportId || null);
  const sourceDetail = useStrategicReport(sourceReportId || null);

  const generateDisabled =
    generate.isPending ||
    !credentialsLoaded ||
    !hasActiveKey ||
    !sourceReportId;

  function onGenerate() {
    if (!sourceReportId) return;
    generate.mutate(
      { source_report_id: sourceReportId },
      {
        onSuccess: (report) => {
          onSelectReport(report.id);
          toast.success("OKR raporu hazır.");
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.status === 503) {
              toast.error("Gemini şu an erişilemiyor: " + err.detail);
              return;
            }
            if (err.status === 400 || err.status === 404 || err.status === 422) {
              toast.error(err.detail);
              return;
            }
          }
          toast.error("OKR raporu üretilemedi.");
        },
      },
    );
  }

  const swotItems = swotList.data?.items ?? [];

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">OKR raporu üret</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">
            OKR&apos;lar mevcut bir SWOT raporundan türetilir — önce bir
            SWOT seçin, ardından Gemini hedef-anahtar sonuç önerisi üretir.
          </p>
          <div>
            <Label className="text-xs">Kaynak SWOT</Label>
            {swotList.isLoading ? (
              <p className="text-muted-foreground mt-1 text-sm">
                <Loader2 className="mr-1 inline size-3 animate-spin" />
                SWOT listesi yükleniyor…
              </p>
            ) : swotItems.length === 0 ? (
              <p className="text-muted-foreground mt-1 text-sm">
                Önce bir SWOT raporu üretmeniz gerekir.
              </p>
            ) : (
              <select
                value={sourceReportId}
                onChange={(e) => onSourceReportChange(e.target.value)}
                className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
              >
                <option value="">Bir SWOT seçin…</option>
                {swotItems.map((r) => (
                  <option key={r.id} value={r.id}>
                    {formatSwotOption(r)}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <Button
              onClick={onGenerate}
              disabled={generateDisabled}
              className="gap-2"
            >
              {generate.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Target className="size-4" aria-hidden />
              )}
              OKR üret
            </Button>
            {!hasActiveKey && credentialsLoaded && (
              <p className="text-muted-foreground mt-2 text-xs">
                Aktif Gemini anahtarı yok — yukarıdaki uyarıdan eklemeniz
                gerekir.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {reportId && detail.data && detail.data.report_type === "okr" && (
        <OkrViewer report={detail.data} sourceReport={sourceDetail.data ?? null} />
      )}
      {reportId && detail.isLoading && (
        <Card>
          <CardContent className="flex items-center gap-2 p-6 text-sm">
            <Loader2 className="size-4 animate-spin" /> Rapor yükleniyor…
          </CardContent>
        </Card>
      )}
      {reportId && detail.isError && (
        <Card>
          <CardContent className="text-destructive p-6 text-sm">
            Rapor yüklenemedi.
          </CardContent>
        </Card>
      )}
    </>
  );
}

function formatSwotOption(r: StrategicReportSummary): string {
  const created = new Date(r.created_at).toLocaleDateString("tr-TR");
  const range =
    r.date_from && r.date_to
      ? `${r.date_from} → ${r.date_to}`
      : "tüm dönem";
  return `${created} · ${range}`;
}

// --- OKR viewer ------------------------------------------------------

function OkrViewer({
  report,
  sourceReport,
}: {
  report: StrategicReportDetail;
  sourceReport: StrategicReportDetail | null;
}) {
  const payload = report.output_payload as unknown as OkrPayload;
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="text-base">OKR Raporu</CardTitle>
          <p className="text-muted-foreground mt-1 text-xs">
            <ReportMeta report={report} />
            {sourceReport && (
              <>
                {" · Kaynak SWOT: "}
                {new Date(sourceReport.created_at).toLocaleDateString("tr-TR")}
              </>
            )}
          </p>
        </div>
        <DownloadPdfButton reportId={report.id} reportType="okr" />
      </CardHeader>
      <CardContent className="space-y-4">
        {payload.objectives.length === 0 ? (
          <p className="text-muted-foreground text-sm">Hedef yok.</p>
        ) : (
          <ul className="space-y-4">
            {payload.objectives.map((obj, idx) => (
              <li
                key={idx}
                className="bg-card space-y-3 rounded-lg border p-4"
              >
                <div>
                  <p className="text-sm font-semibold">
                    Hedef {idx + 1}: {obj.objective}
                  </p>
                  {obj.rationale && (
                    <p className="text-muted-foreground mt-1 text-xs italic">
                      Gerekçe: {obj.rationale}
                    </p>
                  )}
                </div>
                <div>
                  <p className="text-xs font-medium">Anahtar Sonuçlar</p>
                  <ul className="mt-2 space-y-2">
                    {obj.key_results.map((kr, krIdx) => (
                      <li
                        key={krIdx}
                        className="bg-muted/40 rounded border p-3 text-sm"
                      >
                        <p className="font-medium">{kr.text}</p>
                        <dl className="text-muted-foreground mt-1 grid grid-cols-3 gap-2 text-xs">
                          <div>
                            <dt>Metrik</dt>
                            <dd className="text-foreground">{kr.metric}</dd>
                          </div>
                          <div>
                            <dt>Mevcut</dt>
                            <dd className="text-foreground">{kr.baseline}</dd>
                          </div>
                          <div>
                            <dt>Hedef</dt>
                            <dd className="text-foreground">{kr.target}</dd>
                          </div>
                        </dl>
                      </li>
                    ))}
                  </ul>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

// --- History tab -----------------------------------------------------

const PAGE_SIZE = 20;

function HistoryTab({
  reportType,
  onReportTypeChange,
  onOpenReport,
}: {
  reportType: string;
  onReportTypeChange: (value: string) => void;
  onOpenReport: (id: string, type: StrategicReportType) => void;
}) {
  const [offset, setOffset] = useState(0);
  // Reset paginator when the filter changes — otherwise switching swot
  // ↔ okr while on page 3 leaves the offset past the new list's end.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOffset(0);
  }, [reportType]);

  const list = useStrategicReports({
    report_type: (reportType as StrategicReportType) || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const hasMore = list.data?.has_more ?? false;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Rapor geçmişi</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Label className="text-xs">Tür</Label>
          <select
            value={reportType}
            onChange={(e) => onReportTypeChange(e.target.value)}
            className="border-input bg-background rounded-md border px-2 py-1 text-sm"
          >
            <option value="">Tümü</option>
            <option value="swot">SWOT</option>
            <option value="okr">OKR</option>
          </select>
          <span className="text-muted-foreground text-xs">
            {total} kayıt
          </span>
        </div>

        {list.isLoading ? (
          <p className="flex items-center gap-2 py-6 text-sm">
            <Loader2 className="size-4 animate-spin" /> Yükleniyor…
          </p>
        ) : list.isError ? (
          <p className="text-destructive py-6 text-sm">
            Geçmiş yüklenemedi.
          </p>
        ) : items.length === 0 ? (
          <p className="text-muted-foreground py-6 text-sm">
            Henüz rapor yok.
          </p>
        ) : (
          <ul className="divide-y">
            {items.map((r) => (
              <li
                key={r.id}
                className="flex flex-wrap items-center gap-3 py-3"
              >
                <Badge
                  variant="outline"
                  className={
                    r.report_type === "swot"
                      ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                      : "border-indigo-300 bg-indigo-50 text-indigo-800"
                  }
                >
                  {r.report_type === "swot" ? "SWOT" : "OKR"}
                </Badge>
                <div className="flex-1">
                  <p className="text-sm font-medium">
                    {new Date(r.created_at).toLocaleString("tr-TR")}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {r.report_type === "swot"
                      ? r.date_from && r.date_to
                        ? `${r.date_from} → ${r.date_to}`
                        : "tüm dönem"
                      : `kaynak SWOT: ${r.source_report_id?.slice(0, 8) ?? "-"}…`}
                    {r.model_name && ` · ${r.model_name}`}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onOpenReport(r.id, r.report_type)}
                  className="gap-1"
                >
                  Görüntüle <ExternalLink className="size-3.5" aria-hidden />
                </Button>
                <DownloadPdfButton
                  reportId={r.id}
                  reportType={r.report_type}
                  size="sm"
                  variant="outline"
                />
              </li>
            ))}
          </ul>
        )}

        {(offset > 0 || hasMore) && (
          <div className="flex items-center justify-between pt-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            >
              Önceki
            </Button>
            <span className="text-muted-foreground text-xs">
              {offset + 1}–{Math.min(offset + items.length, total)} / {total}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={!hasMore}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
            >
              Sonraki
            </Button>
          </div>
        )}

        <Button
          variant="ghost"
          size="sm"
          onClick={() => list.refetch()}
          disabled={list.isFetching}
          className="gap-1"
        >
          <RefreshCw
            className={`size-3.5 ${list.isFetching ? "animate-spin" : ""}`}
            aria-hidden
          />
          Yenile
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Shared bits -----------------------------------------------------

function ReportMeta({ report }: { report: StrategicReportDetail }) {
  const created = new Date(report.created_at).toLocaleString("tr-TR");
  const range =
    report.date_from && report.date_to
      ? ` · ${report.date_from} → ${report.date_to}`
      : "";
  return (
    <>
      {created}
      {range}
      {report.model_name && ` · ${report.model_name}`}
      {report.token_usage &&
        ` · ${report.token_usage.total.toLocaleString("tr-TR")} token`}
    </>
  );
}

function DownloadPdfButton({
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
  const [pending, setPending] = useState(false);
  return (
    <Button
      variant={variant}
      size={size}
      disabled={pending}
      onClick={async () => {
        setPending(true);
        try {
          await downloadStrategicPdf(reportId, reportType);
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

async function downloadStrategicPdf(
  reportId: string,
  reportType: StrategicReportType,
): Promise<void> {
  // Same fetch+blob+anchor pattern as /reports — bearer header has to
  // travel on the request, which a plain <a download> can't do.
  const accessToken = tokenStorage.getAccessToken();
  if (!accessToken) {
    toast.error("Oturum süresi dolmuş, lütfen tekrar giriş yapın.");
    return;
  }
  // Backend route is /download.pdf (per imga-api routes/strategic_
  // reports.py); the bare /pdf shape returned 404 in production.
  const path = `/tenants/me/strategic-reports/${reportId}/download.pdf`;
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      toast.error(`İndirilemedi: ${res.status} ${detail.slice(0, 80)}`);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download =
      res.headers
        .get("content-disposition")
        ?.match(/filename="?([^"]+)"?/)?.[1] ??
      `imga-${reportType}-${reportId.slice(0, 8)}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch {
    toast.error("İndirme başlatılamadı.");
  }
}


// Sprint 8.3.10 — extract SWOT recommendations into trackable
// action items. Uses the dedicated useExtractFromReport hook so
// the cache invalidation lines up with /action-items.
function ExtractActionItemsButton({ reportId }: { reportId: string }) {
  const router = useRouter();
  const extract = useExtractFromReport();
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={extract.isPending}
      onClick={() =>
        extract.mutate(reportId, {
          onSuccess: (rows) => {
            toast.success(
              `${rows.length} aksiyon eklendi.`,
              {
                action: {
                  label: "Görüntüle",
                  onClick: () => router.push("/action-items"),
                },
              },
            );
          },
          onError: () => toast.error("Aksiyon çıkarma başarısız."),
        })
      }
      className="gap-1"
    >
      {extract.isPending && (
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
      )}
      Aksiyon olarak çıkar
    </Button>
  );
}
