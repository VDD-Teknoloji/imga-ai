"use client";

// Sprint 9.3 A — /admin/llm-audit.
//
// Tenant-admin-only audit dashboard. Three regions:
//   1. Summary cards: total calls, total failures, total tokens.
//   2. 30-day chart (text-grid for now — no recharts dep gymnastics).
//   3. Filterable list with detail expand.
//
// Sprint 9.4 H — Suspense wrapper + Path B URL-state mirror so the
// call_type + success filters survive F5 + back/forward + share-link.

import { AlertTriangle, CheckCircle2, Cpu, Loader2 } from "lucide-react";
import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { type LlmCallAuditRow, useLlmAuditList, useLlmAuditSummary } from "@/hooks/use-llm-audit";
import { useTranslation } from "@/lib/i18n/use-translation";
import { cn } from "@/lib/utils";

const CALL_TYPES = [
  { value: "", labelKey: "admin.llmAudit.callType.all" },
  { value: "classification", labelKey: "admin.llmAudit.callType.classification" },
  { value: "briefing", labelKey: "admin.llmAudit.callType.briefing" },
  { value: "strategic_report", labelKey: "admin.llmAudit.callType.strategicReport" },
  { value: "action_extraction", labelKey: "admin.llmAudit.callType.actionExtraction" },
  { value: "okr", labelKey: "admin.llmAudit.callType.okr" },
];

export default function LlmAuditPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <LlmAuditPageInner />
    </Suspense>
  );
}

function PageSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:p-8">
      <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
    </main>
  );
}

function LlmAuditPageInner() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Path B mirror — local state seeded from URL, re-synced on URL
  // change (back/forward, deep-link). Empty string means "no filter"
  // for both axes; success encodes ``ok`` / ``fail`` so the URL stays
  // human-readable instead of ``success=true``.
  const [callType, setCallType] = useState<string>(() => searchParams.get("call_type") ?? "");
  const [successFilter, setSuccessFilter] = useState<string>(
    () => searchParams.get("success") ?? "",
  );

  useEffect(() => {
    const ct = searchParams.get("call_type") ?? "";
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCallType((prev) => (prev === ct ? prev : ct));
    const sf = searchParams.get("success") ?? "";
    setSuccessFilter((prev) => (prev === sf ? prev : sf));
  }, [searchParams]);

  const updateFilter = useCallback(
    (key: "call_type" | "success", next: string) => {
      if (key === "call_type") setCallType(next);
      else setSuccessFilter(next);
      const params = new URLSearchParams(searchParams);
      if (next === "") {
        params.delete(key);
      } else {
        params.set(key, next);
      }
      const qs = params.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname);
    },
    [pathname, router, searchParams],
  );

  const summary = useLlmAuditSummary();
  const list = useLlmAuditList({
    call_type: callType || undefined,
    success: successFilter === "ok" ? true : successFilter === "fail" ? false : undefined,
    limit: 200,
  });

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Cpu className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("admin.llmAudit.title")}
          </h1>
          <p className="text-muted-foreground text-sm">{t("admin.llmAudit.subtitle")}</p>
        </div>
      </header>

      {summary.data && (
        <div className="grid gap-3 md:grid-cols-3">
          <SummaryCard
            label={t("admin.llmAudit.summary.totalCalls")}
            value={summary.data.total_calls.toLocaleString("tr-TR")}
          />
          <SummaryCard
            label={t("admin.llmAudit.summary.failures")}
            value={summary.data.total_failures.toLocaleString("tr-TR")}
            tone={summary.data.total_failures > 0 ? "warn" : "ok"}
          />
          <SummaryCard
            label={t("admin.llmAudit.summary.totalTokens")}
            value={summary.data.total_tokens.toLocaleString("tr-TR")}
          />
        </div>
      )}

      {summary.data && summary.data.days.length > 0 && (
        <Card>
          <CardContent className="space-y-2 p-4">
            <h2 className="text-sm font-semibold">{t("admin.llmAudit.dailyChart")}</h2>
            <div className="space-y-1 font-mono text-xs">
              {summary.data.days.slice(-30).map((d) => (
                <div key={d.day} className="flex items-center gap-3">
                  <span className="text-muted-foreground w-24 tabular-nums">{d.day}</span>
                  <div className="bg-muted h-2 flex-1 overflow-hidden rounded">
                    <div
                      className="h-full bg-emerald-500"
                      style={{
                        width: `${
                          summary.data &&
                          summary.data.days.reduce((m, x) => Math.max(m, x.total_tokens), 1)
                            ? (d.total_tokens /
                                summary.data.days.reduce(
                                  (m, x) => Math.max(m, x.total_tokens),
                                  1,
                                )) *
                              100
                            : 0
                        }%`,
                      }}
                    />
                  </div>
                  <span className="w-20 text-right tabular-nums">
                    {d.total_tokens.toLocaleString("tr-TR")}
                  </span>
                  <span className="text-muted-foreground w-12 text-right tabular-nums">
                    {d.call_count}
                  </span>
                  {d.failure_count > 0 && (
                    <span className="text-red-600 tabular-nums">↯{d.failure_count}</span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <select
          value={callType}
          onChange={(e) => updateFilter("call_type", e.target.value)}
          className="border-input bg-background rounded-md border px-2 py-1 text-sm"
        >
          {CALL_TYPES.map((o) => (
            <option key={o.value || "all"} value={o.value}>
              {t(o.labelKey)}
            </option>
          ))}
        </select>
        <select
          value={successFilter}
          onChange={(e) => updateFilter("success", e.target.value)}
          className="border-input bg-background rounded-md border px-2 py-1 text-sm"
        >
          <option value="">{t("admin.llmAudit.result.all")}</option>
          <option value="ok">{t("admin.llmAudit.result.ok")}</option>
          <option value="fail">{t("admin.llmAudit.result.fail")}</option>
        </select>
        <span className="text-muted-foreground ml-auto text-xs">
          {t("admin.common.recordCount", { n: list.data?.total ?? 0 })}
        </span>
      </div>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : list.isError ? (
        <p className="text-destructive text-sm">{t("admin.common.listError")}</p>
      ) : !list.data || list.data.items.length === 0 ? (
        <p className="text-muted-foreground p-6 text-center text-sm">
          {t("admin.common.noRecords")}
        </p>
      ) : (
        <ul className="space-y-2">
          {list.data.items.map((row) => (
            <AuditRow key={row.id} row={row} />
          ))}
        </ul>
      )}
    </main>
  );
}

function SummaryCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn";
}) {
  return (
    <Card
      className={cn(
        "border-2",
        tone === "warn"
          ? "border-amber-300"
          : tone === "ok"
            ? "border-emerald-300"
            : "border-zinc-200",
      )}
    >
      <CardContent className="space-y-1 p-3">
        <p className="text-muted-foreground text-xs">{label}</p>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}

function AuditRow({ row }: { row: LlmCallAuditRow }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="bg-card rounded-lg border p-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-wrap items-center gap-2 text-left"
      >
        {row.success ? (
          <CheckCircle2 className="size-4 text-emerald-600" aria-hidden />
        ) : (
          <AlertTriangle className="size-4 text-red-600" aria-hidden />
        )}
        <span className="text-sm font-medium">{row.call_type}</span>
        <Badge variant="outline" className="text-xs">
          {row.model_name}
        </Badge>
        {row.fallback_used && (
          <Badge className="bg-amber-100 text-xs text-amber-900 hover:bg-amber-100">
            keyword fallback
          </Badge>
        )}
        {row.error_type && (
          <Badge className="bg-red-100 text-xs text-red-900 hover:bg-red-100">
            {row.error_type}
          </Badge>
        )}
        <span className="text-muted-foreground text-xs">
          {row.total_tokens ?? 0} tok · {row.duration_ms ?? "?"}ms
        </span>
        <span className="text-muted-foreground ml-auto text-xs tabular-nums">
          {new Date(row.created_at).toLocaleString("tr-TR")}
        </span>
      </button>
      {expanded && (
        <dl className="mt-3 grid gap-1 border-t pt-3 text-xs md:grid-cols-2">
          {row.prompt_template_key && (
            <DetailLine
              label={t("admin.llmAudit.detail.prompt")}
              value={`${row.prompt_template_key}@${row.prompt_template_version}`}
            />
          )}
          <DetailLine
            label={t("admin.llmAudit.detail.promptHash")}
            value={row.prompt_hash.slice(0, 16) + "…"}
          />
          <DetailLine label={t("admin.llmAudit.detail.provider")} value={row.model_provider} />
          {row.input_tokens !== null && (
            <DetailLine
              label={t("admin.llmAudit.detail.tokensInOut")}
              value={`${row.input_tokens} / ${row.output_tokens ?? 0}`}
            />
          )}
          {row.request_id && (
            <DetailLine label={t("admin.llmAudit.detail.requestId")} value={row.request_id} />
          )}
          {row.error_message && (
            <DetailLine
              label={t("admin.llmAudit.detail.error")}
              value={row.error_message.slice(0, 200)}
              tone="warn"
            />
          )}
        </dl>
      )}
    </li>
  );
}

function DetailLine({ label, value, tone }: { label: string; value: string; tone?: "warn" }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted-foreground w-32 shrink-0">{label}</dt>
      <dd className={cn("min-w-0 break-all", tone === "warn" && "text-red-700")}>{value}</dd>
    </div>
  );
}
