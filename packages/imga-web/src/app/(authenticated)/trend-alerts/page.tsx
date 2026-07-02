"use client";

// Sprint 8.3.10 — /trend-alerts.
//
// KPI deviation alert log. Manual evaluate trigger (admin only;
// the cron driver lands in Sprint 8.6 alongside Prometheus).

import { Check, Loader2, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useTranslation } from "@/lib/i18n/use-translation";
import {
  useEvaluateTrendAlerts,
  useTrendAlerts,
  useUpdateTrendAlert,
} from "@/hooks/use-trend-alerts";
import {
  TREND_ALERT_SEVERITY_LABELS,
  type TrendAlert,
  type TrendAlertSeverity,
  type TrendAlertStatus,
} from "@/lib/types";

const SEVERITY_TONE: Record<TrendAlertSeverity, string> = {
  info: "border-blue-300 bg-blue-50 text-blue-800",
  warning: "border-amber-300 bg-amber-50 text-amber-800",
  critical: "border-red-300 bg-red-50 text-red-800",
};

export default function TrendAlertsPage() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <Content />
    </Suspense>
  );
}

function HeaderSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("dashboard.trendAlerts.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("dashboard.common.loading")}
        </p>
      </header>
    </main>
  );
}

function Content() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [statusFilter, setStatusFilterState] = useState<
    TrendAlertStatus | "all"
  >(
    () =>
      (searchParams.get("status") as TrendAlertStatus | "all" | null) ||
      "active",
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const url =
      (searchParams.get("status") as TrendAlertStatus | "all" | null) ||
      "active";
    setStatusFilterState((prev) => (prev === url ? prev : url));
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParam(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "active") params.delete("status");
    else params.set("status", value);
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const list = useTrendAlerts(statusFilter);
  const evaluate = useEvaluateTrendAlerts();

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("dashboard.trendAlerts.title")}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t("dashboard.trendAlerts.subtitle")}
          </p>
        </div>
        <Button
          onClick={() =>
            evaluate.mutate(undefined, {
              onSuccess: (rows) =>
                toast.success(
                  t("dashboard.trendAlerts.newAlerts", { n: rows.length }),
                ),
              onError: () =>
                toast.error(t("dashboard.trendAlerts.evalFailed")),
            })
          }
          disabled={evaluate.isPending}
          className="gap-2"
        >
          {evaluate.isPending && <Loader2 className="size-4 animate-spin" />}
          {t("dashboard.trendAlerts.evaluateNow")}
        </Button>
      </header>

      <div className="bg-card ring-foreground/5 shadow-soft flex flex-wrap items-center gap-3 rounded-2xl p-4 ring-1">
        <Label className="text-xs">
          {t("dashboard.trendAlerts.filter.status")}
        </Label>
        <select
          value={statusFilter}
          onChange={(e) => {
            const next = e.target.value as TrendAlertStatus | "all";
            setStatusFilterState(next);
            pushParam(next);
          }}
          className="border-input bg-background rounded-md border px-2 py-1 text-sm"
        >
          <option value="active">
            {t("dashboard.trendAlerts.status.active")}
          </option>
          <option value="acknowledged">
            {t("dashboard.trendAlerts.status.acknowledged")}
          </option>
          <option value="dismissed">
            {t("dashboard.trendAlerts.status.dismissed")}
          </option>
          <option value="all">{t("dashboard.trendAlerts.status.all")}</option>
        </select>
      </div>

      {list.isLoading ? (
        <p className="text-sm">{t("dashboard.common.loading")}</p>
      ) : list.isError ? (
        <p className="text-destructive text-sm">
          {t("dashboard.trendAlerts.listFailed")}
        </p>
      ) : !list.data || list.data.length === 0 ? (
        <p className="text-muted-foreground p-6 text-center text-sm">
          {t("dashboard.trendAlerts.empty")}
        </p>
      ) : (
        <ul className="space-y-2">
          {list.data.map((a) => (
            <AlertRow key={a.id} alert={a} />
          ))}
        </ul>
      )}
    </main>
  );
}

function AlertRow({ alert }: { alert: TrendAlert }) {
  const { t } = useTranslation();
  const update = useUpdateTrendAlert();
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div>
          <CardTitle className="text-base">{alert.title}</CardTitle>
          <p className="text-muted-foreground text-xs">
            {new Date(alert.created_at).toLocaleString("tr-TR")} ·{" "}
            <code>{alert.alert_type}</code>
          </p>
        </div>
        <Badge
          variant="outline"
          className={`text-xs ${SEVERITY_TONE[alert.severity]}`}
        >
          {TREND_ALERT_SEVERITY_LABELS[alert.severity]}
        </Badge>
      </CardHeader>
      <CardContent>
        <p className="text-sm">{alert.description}</p>
        {alert.status === "active" && (
          <div className="mt-3 flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                update.mutate({ id: alert.id, status: "acknowledged" })
              }
              disabled={update.isPending}
              className="gap-1"
            >
              <Check className="size-3.5" />{" "}
              {t("dashboard.trendAlerts.acknowledge")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                update.mutate({ id: alert.id, status: "dismissed" })
              }
              disabled={update.isPending}
              className="gap-1"
            >
              <X className="size-3.5" /> {t("dashboard.trendAlerts.dismiss")}
            </Button>
          </div>
        )}
        {alert.status !== "active" && (
          <p className="text-muted-foreground mt-2 text-xs">
            {alert.status === "acknowledged"
              ? t("dashboard.trendAlerts.acknowledged")
              : t("dashboard.trendAlerts.dismissed")}{" "}
            {alert.acknowledged_at &&
              new Date(alert.acknowledged_at).toLocaleString("tr-TR")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
