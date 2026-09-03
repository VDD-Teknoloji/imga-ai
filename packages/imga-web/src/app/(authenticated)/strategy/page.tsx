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
  ExternalLink,
  History,
  LayoutGrid,
  Loader2,
  RefreshCw,
  Sparkles,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { BatchFilterDropdown } from "@/components/reviews/batch-filter-dropdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLlmCredentials } from "@/hooks/use-llm-credentials";
import {
  useGenerateOkr,
  useGenerateSwot,
  useStrategicReport,
  useStrategicReports,
} from "@/hooks/use-strategic-reports";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { StrategicReportSummary, StrategicReportType } from "@/lib/types";

import { DownloadPdfButton } from "./_components/download-pdf-button";
import { OkrViewer } from "./_components/okr-board";
import { SwotViewer } from "./_components/swot-grid";

type TabKey = "swot" | "okr" | "history";

const TAB_KEYS: Record<TabKey, string> = {
  swot: "dashboard.strategy.tab.swot",
  okr: "dashboard.strategy.tab.okr",
  history: "dashboard.strategy.tab.history",
};

const TAB_ICONS: Record<TabKey, LucideIcon> = {
  swot: LayoutGrid,
  okr: Target,
  history: History,
};

export default function StrategyPage() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <StrategyContent />
    </Suspense>
  );
}

function HeaderSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="flex items-center gap-2.5 text-2xl font-semibold tracking-tight md:text-3xl">
          <span className="bg-muted text-muted-foreground inline-flex size-7 shrink-0 items-center justify-center rounded-lg">
            <Compass className="size-4" aria-hidden />
          </span>
          {t("dashboard.strategy.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("dashboard.common.loading")}</p>
      </header>
    </main>
  );
}

function StrategyContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { t } = useTranslation();

  // URL → state mirror (Sprint 8.3.4 round-2 / 8.3.5.6 round-2 pattern).
  // useSearchParams stops notifying inside Suspense after the first
  // hydration; controlled primitives need a local state copy plus a
  // sync effect for back/forward navigation.
  const [tab, setTabState] = useState<TabKey>(() => (searchParams.get("tab") as TabKey) || "swot");
  const [dateFrom, setDateFromState] = useState<string>(() => searchParams.get("date_from") ?? "");
  const [dateTo, setDateToState] = useState<string>(() => searchParams.get("date_to") ?? "");
  const [reportId, setReportIdState] = useState<string>(() => searchParams.get("report_id") ?? "");
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
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="flex items-center gap-2.5 text-2xl font-semibold tracking-tight md:text-3xl">
          <span className="bg-muted text-muted-foreground inline-flex size-7 shrink-0 items-center justify-center rounded-lg">
            <Compass className="size-4" aria-hidden />
          </span>
          {t("dashboard.strategy.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("dashboard.strategy.subtitle")}</p>
      </header>

      {credentialsLoaded && !hasActiveKey && (
        <NoCredentialBanner onNavigate={() => router.push("/settings/integrations")} />
      )}

      <Tabs value={tab} onValueChange={(v) => handleTabChange(v as TabKey)}>
        <TabsList className="grid w-full grid-cols-3 sm:w-fit">
          {(Object.keys(TAB_KEYS) as TabKey[]).map((k) => {
            const Icon = TAB_ICONS[k];
            return (
              <TabsTrigger key={k} value={k}>
                <Icon className="size-3.5" aria-hidden />
                {t(TAB_KEYS[k])}
              </TabsTrigger>
            );
          })}
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
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-5 sm:flex-row sm:items-center sm:justify-between dark:border-amber-900/50 dark:bg-amber-950/30">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 text-amber-600" aria-hidden />
        <div className="text-sm">
          <p className="font-medium text-amber-900">{t("dashboard.strategy.banner.title")}</p>
          <p className="text-amber-800">{t("dashboard.strategy.banner.desc")}</p>
        </div>
      </div>
      <Button onClick={onNavigate} variant="outline" className="shrink-0 gap-2">
        {t("dashboard.strategy.banner.addKey")} <ArrowRight className="size-4" aria-hidden />
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
  const { t } = useTranslation();
  const generate = useGenerateSwot();
  const detail = useStrategicReport(reportId || null);
  const [forceRefresh, setForceRefresh] = useState(false);
  // Sprint 8.3.11 — optional batch scope. When set, the SWOT only
  // reflects that upload's reviews. The state lives in this tab
  // (not the parent) because /strategy doesn't otherwise share the
  // batch param across tabs — OKR inherits via source SWOT.
  const [batchScopeId, setBatchScopeId] = useState<string | undefined>(undefined);

  const generateDisabled = generate.isPending || !credentialsLoaded || !hasActiveKey;

  function onGenerate() {
    generate.mutate(
      {
        date_from: dateFrom || null,
        date_to: dateTo || null,
        force_refresh: forceRefresh,
        batch_id: batchScopeId ?? null,
      },
      {
        onSuccess: (report) => {
          onSelectReport(report.id);
          toast.success(t("dashboard.strategy.swot.ready"));
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.status === 503) {
              toast.error(
                t("dashboard.strategy.geminiUnavailable", {
                  detail: err.detail,
                }),
              );
              return;
            }
            if (err.status === 400 || err.status === 422) {
              toast.error(err.detail);
              return;
            }
          }
          toast.error(t("dashboard.strategy.swot.generateFailed"));
        },
      },
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("dashboard.strategy.swot.cardTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">{t("dashboard.strategy.swot.cardDesc")}</p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <Label className="text-xs">{t("dashboard.strategy.field.startDate")}</Label>
              <input
                type="date"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={(e) => onDateFromChange(e.target.value)}
                className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
              />
            </div>
            <div>
              <Label className="text-xs">{t("dashboard.strategy.field.endDate")}</Label>
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
                {t("dashboard.strategy.swot.skipCache")}
              </label>
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("dashboard.strategy.swot.batchScopeLabel")}</Label>
            <BatchFilterDropdown
              selected={batchScopeId}
              onChange={(next) => setBatchScopeId(next)}
            />
            <p className="text-muted-foreground text-xs">
              {t("dashboard.strategy.swot.batchScopeHelp")}
            </p>
          </div>
          <div>
            <Button onClick={onGenerate} disabled={generateDisabled} className="gap-2 rounded-2xl">
              {generate.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Sparkles className="size-4" aria-hidden />
              )}
              {t("dashboard.strategy.swot.generate")}
            </Button>
            {!hasActiveKey && credentialsLoaded && (
              <p className="text-muted-foreground mt-2 text-xs">
                {t("dashboard.strategy.noKeyHint")}
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
            <Loader2 className="size-4 animate-spin" /> {t("dashboard.strategy.reportLoading")}
          </CardContent>
        </Card>
      )}
      {reportId && detail.isError && (
        <Card>
          <CardContent className="text-destructive p-6 text-sm">
            {t("dashboard.strategy.reportLoadFailed")}
          </CardContent>
        </Card>
      )}
    </>
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
  const { t } = useTranslation();
  const swotList = useStrategicReports({ report_type: "swot", limit: 50 });
  const generate = useGenerateOkr();
  const detail = useStrategicReport(reportId || null);
  const sourceDetail = useStrategicReport(sourceReportId || null);

  const generateDisabled =
    generate.isPending || !credentialsLoaded || !hasActiveKey || !sourceReportId;

  function onGenerate() {
    if (!sourceReportId) return;
    generate.mutate(
      { source_report_id: sourceReportId },
      {
        onSuccess: (report) => {
          onSelectReport(report.id);
          toast.success(t("dashboard.strategy.okr.ready"));
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.status === 503) {
              toast.error(
                t("dashboard.strategy.geminiUnavailable", {
                  detail: err.detail,
                }),
              );
              return;
            }
            if (err.status === 400 || err.status === 404 || err.status === 422) {
              toast.error(err.detail);
              return;
            }
          }
          toast.error(t("dashboard.strategy.okr.generateFailed"));
        },
      },
    );
  }

  const swotItems = swotList.data?.items ?? [];

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("dashboard.strategy.okr.cardTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">{t("dashboard.strategy.okr.cardDesc")}</p>
          <div>
            <Label className="text-xs">{t("dashboard.strategy.okr.sourceSwot")}</Label>
            {swotList.isLoading ? (
              <p className="text-muted-foreground mt-1 text-sm">
                <Loader2 className="mr-1 inline size-3 animate-spin" />
                {t("dashboard.strategy.okr.swotListLoading")}
              </p>
            ) : swotItems.length === 0 ? (
              <p className="text-muted-foreground mt-1 text-sm">
                {t("dashboard.strategy.okr.needSwotFirst")}
              </p>
            ) : (
              <select
                value={sourceReportId}
                onChange={(e) => onSourceReportChange(e.target.value)}
                className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
              >
                <option value="">{t("dashboard.strategy.okr.selectSwot")}</option>
                {swotItems.map((r) => (
                  <option key={r.id} value={r.id}>
                    {formatSwotOption(r, t)}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <Button onClick={onGenerate} disabled={generateDisabled} className="gap-2 rounded-2xl">
              {generate.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Sparkles className="size-4" aria-hidden />
              )}
              {t("dashboard.strategy.okr.generate")}
            </Button>
            {!hasActiveKey && credentialsLoaded && (
              <p className="text-muted-foreground mt-2 text-xs">
                {t("dashboard.strategy.noKeyHint")}
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
            <Loader2 className="size-4 animate-spin" /> {t("dashboard.strategy.reportLoading")}
          </CardContent>
        </Card>
      )}
      {reportId && detail.isError && (
        <Card>
          <CardContent className="text-destructive p-6 text-sm">
            {t("dashboard.strategy.reportLoadFailed")}
          </CardContent>
        </Card>
      )}
    </>
  );
}

function formatSwotOption(r: StrategicReportSummary, t: (key: string) => string): string {
  const created = new Date(r.created_at).toLocaleDateString("tr-TR");
  const range =
    r.date_from && r.date_to ? `${r.date_from} → ${r.date_to}` : t("dashboard.strategy.allPeriod");
  return `${created} · ${range}`;
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
  const { t } = useTranslation();
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
        <CardTitle className="text-base">{t("dashboard.strategy.history.cardTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Label className="text-xs">{t("dashboard.strategy.history.type")}</Label>
          <select
            value={reportType}
            onChange={(e) => onReportTypeChange(e.target.value)}
            className="border-input bg-background rounded-md border px-2 py-1 text-sm"
          >
            <option value="">{t("dashboard.common.all")}</option>
            <option value="swot">SWOT</option>
            <option value="okr">OKR</option>
          </select>
          <span className="text-muted-foreground text-xs">
            {t("dashboard.strategy.history.recordsCount", { n: total })}
          </span>
        </div>

        {list.isLoading ? (
          <p className="flex items-center gap-2 py-6 text-sm">
            <Loader2 className="size-4 animate-spin" /> {t("dashboard.common.loading")}
          </p>
        ) : list.isError ? (
          <p className="text-destructive py-6 text-sm">
            {t("dashboard.strategy.history.loadFailed")}
          </p>
        ) : items.length === 0 ? (
          <p className="text-muted-foreground py-6 text-sm">
            {t("dashboard.strategy.history.empty")}
          </p>
        ) : (
          <ul className="divide-y">
            {items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 py-3">
                <Badge
                  variant="outline"
                  className={
                    r.report_type === "swot"
                      ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                      : "border-primary/30 bg-accent text-accent-foreground"
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
                        : t("dashboard.strategy.allPeriod")
                      : t("dashboard.strategy.history.sourceSwot", {
                          id: r.source_report_id?.slice(0, 8) ?? "-",
                        })}
                    {r.model_name && ` · ${r.model_name}`}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onOpenReport(r.id, r.report_type)}
                  className="gap-1"
                >
                  {t("dashboard.common.view")} <ExternalLink className="size-3.5" aria-hidden />
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
              {t("dashboard.strategy.pager.prev")}
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
              {t("dashboard.strategy.pager.next")}
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
          <RefreshCw className={`size-3.5 ${list.isFetching ? "animate-spin" : ""}`} aria-hidden />
          {t("dashboard.strategy.refresh")}
        </Button>
      </CardContent>
    </Card>
  );
}
