"use client";

// C1/C2 (2026-08-20 süper-admin envanteri) — /admin/usage "Platform
// Kullanımı". İki bölge:
//   1. Sistem sağlığı şeridi (Redis + arq kuyruk/worker + son 7 gün
//      batch job durum dağılımı) — /admin/system-health, best-effort.
//   2. Tarih aralıklı LLM kullanım + maliyet raporu (platform kartları
//      + kurum kırılımı + call_type kırılımı) — /admin/llm-usage.
//
// /admin/tenants ile aynı öz-koruma deseni (isSuperAdmin — bu sayfa da
// yalnız süper yönetici, tenant_admin dahil değil). Suspense + Path B
// URL-state (date_from/date_to) — bkz. docs/agent-rules/url-state-patterns.md.

import { Gauge } from "lucide-react";
import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { AdminSummaryCard } from "@/components/admin/admin-summary-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { DateField } from "@/components/ui/date-field";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CALL_TYPE_LABEL_KEYS } from "@/hooks/use-llm-audit";
import {
  type AdminLlmUsageByCallType,
  type AdminLlmUsageByTenant,
  useAdminLlmUsage,
  useAdminSystemHealth,
} from "@/hooks/use-admin-usage";
import { useAuthStore } from "@/lib/auth-store";
import { useTranslation } from "@/lib/i18n/use-translation";
import { formatCompactNumber, formatUsd } from "@/lib/number-format";
import { cn } from "@/lib/utils";

export default function AdminUsagePage() {
  const isSuperAdmin = useAuthStore((s) => s.user?.is_super_admin ?? false);
  if (!isSuperAdmin) {
    return <ForbiddenView />;
  }
  return (
    <Suspense fallback={<PageSkeleton />}>
      <AdminUsagePageInner />
    </Suspense>
  );
}

function ForbiddenView() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-3xl p-6 md:p-8">
      <div className="bg-card space-y-2 rounded-lg border p-8 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">{t("common.forbidden.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("common.forbidden.desc.super")}</p>
      </div>
    </main>
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

function AdminUsagePageInner() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Path B mirror — "" bedeni "seçili değil, backend varsayılanı (son
  // 30 gün) uygulasın" demek.
  const [dateFrom, setDateFrom] = useState<string>(() => searchParams.get("date_from") ?? "");
  const [dateTo, setDateTo] = useState<string>(() => searchParams.get("date_to") ?? "");

  useEffect(() => {
    const f = searchParams.get("date_from") ?? "";
    const to = searchParams.get("date_to") ?? "";
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDateFrom((prev) => (prev === f ? prev : f));
    setDateTo((prev) => (prev === to ? prev : to));
    // INTENT: URL is source of truth; mirror onto local state on
    // navigation events (back/forward, deep-link, F5 hydration race).
  }, [searchParams]);

  // Her iki tarihi BİRLİKTE yaz: yalnız biri güncellenirse backend
  // _day_bounds() diğerini kendi varsayılanına göre yeniden hesaplar
  // (routes/admin/llm_usage.py) ve görünen aralık URL'den sessizce
  // kayar. Callers her zaman güncel iki değeri de geçirir.
  const applyRange = useCallback(
    (nextFrom: string, nextTo: string) => {
      setDateFrom(nextFrom);
      setDateTo(nextTo);
      const params = new URLSearchParams(searchParams.toString());
      if (nextFrom) params.set("date_from", nextFrom);
      else params.delete("date_from");
      if (nextTo) params.set("date_to", nextTo);
      else params.delete("date_to");
      const qs = params.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const health = useAdminSystemHealth();
  const usage = useAdminLlmUsage({
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });

  // Tarih alanları boşken backend'in uyguladığı fiili aralığı (yanıt
  // echo'su) gösterir — kullanıcı hiç seçim yapmadan "son 30 gün"ün
  // hangi tarihler olduğunu görür.
  const displayFrom = dateFrom || usage.data?.date_from || "";
  const displayTo = dateTo || usage.data?.date_to || "";

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Gauge className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("admin.usage.title")}
          </h1>
          <p className="text-muted-foreground text-sm">{t("admin.usage.subtitle")}</p>
        </div>
      </header>

      <SystemHealthStrip health={health} />

      <div className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <span className="text-sm font-medium">{t("admin.usage.range.label")}</span>
        <DateField
          value={displayFrom}
          max={displayTo || undefined}
          aria-label={t("admin.usage.range.fromAria")}
          onChange={(e) => applyRange(e.target.value, dateTo)}
        />
        <span className="text-muted-foreground text-xs" aria-hidden>
          –
        </span>
        <DateField
          value={displayTo}
          min={displayFrom || undefined}
          aria-label={t("admin.usage.range.toAria")}
          onChange={(e) => applyRange(dateFrom, e.target.value)}
        />
      </div>

      {usage.isLoading ? (
        <div className="grid gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 w-full rounded-xl" />
          ))}
        </div>
      ) : usage.isError ? (
        <p className="text-destructive text-sm">{t("admin.common.listError")}</p>
      ) : usage.data ? (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <AdminSummaryCard
              label={t("admin.usage.platform.calls")}
              value={usage.data.platform.calls.toLocaleString("tr-TR")}
            />
            <AdminSummaryCard
              label={t("admin.usage.platform.tokens")}
              value={formatCompactNumber(
                usage.data.platform.input_tokens + usage.data.platform.output_tokens,
              )}
            />
            <AdminSummaryCard
              label={t("admin.usage.platform.cost")}
              value={formatUsd(usage.data.platform.total_cost_usd)}
            />
            <AdminSummaryCard
              label={t("admin.usage.platform.errorRate")}
              value={`%${Math.round(usage.data.platform.error_rate * 100)}`}
              tone={usage.data.platform.error_rate > 0.05 ? "warn" : "neutral"}
            />
          </div>

          <TenantUsageTable rows={usage.data.tenants} />
          <CallTypeTable rows={usage.data.call_types} />
        </>
      ) : null}
    </main>
  );
}

function SystemHealthStrip({ health }: { health: ReturnType<typeof useAdminSystemHealth> }) {
  const { t } = useTranslation();

  if (health.isLoading) {
    return <Skeleton className="h-14 w-full rounded-lg" />;
  }
  if (health.isError || !health.data) {
    return <p className="text-destructive text-sm">{t("admin.common.listError")}</p>;
  }
  const d = health.data;

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3 text-sm">
        <span className="inline-flex items-center gap-1.5">
          <span
            className={cn("size-2 rounded-full", d.redis_ok ? "bg-emerald-500" : "bg-red-500")}
            aria-hidden
          />
          {d.redis_ok ? t("admin.usage.health.redisOk") : t("admin.usage.health.redisDown")}
        </span>
        <span className="text-muted-foreground">
          {t("admin.usage.health.queueDepth")}:{" "}
          <strong className="text-foreground tabular-nums">{d.arq_queue_depth ?? "—"}</strong>
        </span>
        <span className="text-muted-foreground">
          {t("admin.usage.health.workers")}:{" "}
          <strong className="text-foreground">{d.workers}</strong>
        </span>
        <span className="flex flex-wrap items-center gap-1.5 sm:ml-auto">
          <span className="text-muted-foreground text-xs">{t("admin.usage.health.jobs7d")}:</span>
          {d.jobs_by_status.length === 0 ? (
            <span className="text-muted-foreground text-xs">{t("admin.common.noRecords")}</span>
          ) : (
            d.jobs_by_status.map((j) => (
              <Badge key={j.status} variant="outline" className="text-xs">
                {jobStatusLabel(j.status, t)}: {j.count}
              </Badge>
            ))
          )}
        </span>
      </CardContent>
    </Card>
  );
}

/** analyze.history.status.* (analyze/upload/history sayfası) etiketlerini
 *  yeniden kullanır — aynı BatchJobStatus enum'u, ikinci bir çeviri
 *  kopyası açmaya gerek yok. Bilinmeyen bir durum gelirse (şema
 *  değişikliği) ham string'e düşer. */
function jobStatusLabel(status: string, t: ReturnType<typeof useTranslation>["t"]): string {
  const key = `analyze.history.status.${status}`;
  const label = t(key);
  return label === key ? status : label;
}

function TenantUsageTable({ rows }: { rows: AdminLlmUsageByTenant[] }) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground p-6 text-center text-sm">{t("admin.common.noRecords")}</p>
    );
  }
  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold">{t("admin.usage.tenantTable")}</h2>
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.field.name")}</TableHead>
              <TableHead className="text-right">{t("admin.usage.col.calls")}</TableHead>
              <TableHead className="hidden text-right sm:table-cell">
                {t("admin.usage.col.inputTokens")}
              </TableHead>
              <TableHead className="hidden text-right sm:table-cell">
                {t("admin.usage.col.outputTokens")}
              </TableHead>
              <TableHead className="text-right">{t("admin.usage.col.cost")}</TableHead>
              <TableHead className="hidden text-right md:table-cell">
                {t("admin.usage.col.unknownCost")}
              </TableHead>
              <TableHead className="text-right">{t("admin.usage.col.errorRate")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.tenant_id}>
                <TableCell className="font-medium">{r.tenant_name}</TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {r.calls.toLocaleString("tr-TR")}
                </TableCell>
                <TableCell className="text-muted-foreground hidden text-right text-xs tabular-nums sm:table-cell">
                  {formatCompactNumber(r.input_tokens)}
                </TableCell>
                <TableCell className="text-muted-foreground hidden text-right text-xs tabular-nums sm:table-cell">
                  {formatCompactNumber(r.output_tokens)}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {formatUsd(r.total_cost_usd)}
                </TableCell>
                <TableCell className="text-muted-foreground hidden text-right text-xs tabular-nums md:table-cell">
                  {r.unknown_cost_calls > 0 ? r.unknown_cost_calls : "—"}
                </TableCell>
                <TableCell
                  className={cn(
                    "text-right text-xs tabular-nums",
                    r.error_rate > 0.05 && "font-medium text-red-600",
                  )}
                >
                  %{Math.round(r.error_rate * 100)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function CallTypeTable({ rows }: { rows: AdminLlmUsageByCallType[] }) {
  const { t } = useTranslation();
  if (rows.length === 0) return null;
  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold">{t("admin.usage.callTypeBreakdown")}</h2>
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.usage.col.callType")}</TableHead>
              <TableHead className="text-right">{t("admin.usage.col.calls")}</TableHead>
              <TableHead className="hidden text-right sm:table-cell">
                {t("admin.usage.col.inputTokens")}
              </TableHead>
              <TableHead className="hidden text-right sm:table-cell">
                {t("admin.usage.col.outputTokens")}
              </TableHead>
              <TableHead className="text-right">{t("admin.usage.col.cost")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const labelKey = CALL_TYPE_LABEL_KEYS[r.call_type];
              return (
                <TableRow key={r.call_type}>
                  <TableCell className="font-medium">
                    {labelKey ? t(labelKey) : r.call_type}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {r.calls.toLocaleString("tr-TR")}
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden text-right text-xs tabular-nums sm:table-cell">
                    {formatCompactNumber(r.input_tokens)}
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden text-right text-xs tabular-nums sm:table-cell">
                    {formatCompactNumber(r.output_tokens)}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {formatUsd(r.total_cost_usd)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
