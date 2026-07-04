"use client";

// Sprint 9.2 B — /settings/kpi-goals.
//
// Per-tenant KPI target list + create form. Pulls the metric
// registry from useMetricDefinitions (Sprint 9.2 A) so the metric
// dropdown labels stay in sync with the backend's seed data; pulls
// active goals via useKpiGoals.

import { Loader2, Target, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type GoalPeriod,
  useCreateKpiGoal,
  useDeleteKpiGoal,
  useKpiGoals,
} from "@/hooks/use-kpi-goals";
import { useMetricDefinitions } from "@/hooks/use-metric-definitions";
import { ApiError, formatApiErrorMessage } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

const PERIODS: ReadonlyArray<GoalPeriod> = [
  "weekly",
  "monthly",
  "quarterly",
  "yearly",
];

export default function KpiGoalsPage() {
  return (
    <RequireRole level="admin">
      <KpiGoalsPageInner />
    </RequireRole>
  );
}

function KpiGoalsPageInner() {
  const goals = useKpiGoals(false); // history + active
  const metrics = useMetricDefinitions();
  const { t } = useTranslation();

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Target className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("settings.kpi.title")}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t("settings.kpi.subtitle")}
          </p>
        </div>
      </header>

      <CreateForm />

      {goals.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : goals.isError ? (
        <p className="text-destructive text-sm">{t("settings.kpi.loadError")}</p>
      ) : !goals.data || goals.data.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-sm text-muted-foreground">
            {t("settings.kpi.empty")}
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-2">
          {goals.data.map((g) => {
            const meta = metrics.data?.find((m) => m.metric_key === g.metric_key);
            return (
              <li
                key={g.id}
                className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-3"
              >
                <div className="flex-1 space-y-0.5">
                  <p className="text-sm font-medium">
                    {meta?.display_name ?? g.metric_key}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {t("settings.kpi.targetLabel")}{" "}
                    <strong>{g.target_value}</strong>
                    {meta?.unit === "percentage" ? "%" : ""} · {g.target_period}{" "}
                    · {g.period_start} → {g.period_end}
                  </p>
                  {g.notes && (
                    <p className="text-muted-foreground line-clamp-2 text-xs">
                      {g.notes}
                    </p>
                  )}
                </div>
                <Badge variant="outline" className="text-xs">
                  {g.target_period}
                </Badge>
                <DeleteButton id={g.id} />
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}

function DeleteButton({ id }: { id: string }) {
  const del = useDeleteKpiGoal();
  const { t } = useTranslation();
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => {
        if (!confirm(t("settings.kpi.deleteConfirm"))) return;
        del.mutate(id, {
          onSuccess: () => toast.success(t("settings.kpi.deleted")),
          onError: (err) => toast.error(formatApiErrorMessage(err)),
        });
      }}
      disabled={del.isPending}
      className="gap-1 text-red-700 hover:text-red-900"
    >
      <Trash2 className="size-3.5" aria-hidden /> {t("settings.common.delete")}
    </Button>
  );
}

function CreateForm() {
  const create = useCreateKpiGoal();
  const metrics = useMetricDefinitions();
  const { t } = useTranslation();
  const [metricKey, setMetricKey] = useState<string>("");
  const [targetValue, setTargetValue] = useState<string>("");
  const [period, setPeriod] = useState<GoalPeriod>("monthly");
  const [periodStart, setPeriodStart] = useState<string>(_todayIso());
  const [periodEnd, setPeriodEnd] = useState<string>(_endOfMonthIso());
  const [notes, setNotes] = useState<string>("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!metricKey) {
      toast.error(t("settings.kpi.selectMetric"));
      return;
    }
    const numericTarget = Number(targetValue);
    if (!Number.isFinite(numericTarget)) {
      toast.error(t("settings.kpi.targetMustBeNumber"));
      return;
    }
    create.mutate(
      {
        metric_key: metricKey,
        target_value: numericTarget,
        target_period: period,
        period_start: periodStart,
        period_end: periodEnd,
        notes: notes || null,
      },
      {
        onSuccess: () => {
          toast.success(t("settings.kpi.added"));
          setMetricKey("");
          setTargetValue("");
          setNotes("");
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error(t("settings.kpi.duplicate"));
          } else {
            toast.error(formatApiErrorMessage(err));
          }
        },
      },
    );
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">{t("settings.kpi.newGoal")}</h2>
        <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">{t("settings.kpi.metric")}</Label>
            <select
              value={metricKey}
              onChange={(e) => setMetricKey(e.target.value)}
              className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm"
            >
              <option value="">{t("settings.kpi.metricPlaceholder")}</option>
              {metrics.data?.map((m) => (
                <option key={m.metric_key} value={m.metric_key}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("settings.kpi.targetValue")}</Label>
            <Input
              type="number"
              step="0.1"
              value={targetValue}
              onChange={(e) => setTargetValue(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("settings.kpi.period")}</Label>
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value as GoalPeriod)}
              className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm"
            >
              {PERIODS.map((p) => (
                <option key={p} value={p}>
                  {t(`settings.kpi.period.${p}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-2 md:col-span-1 md:grid-cols-2">
            <div className="space-y-1">
              <Label className="text-xs">{t("settings.kpi.startDate")}</Label>
              <Input
                type="date"
                value={periodStart}
                onChange={(e) => setPeriodStart(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t("settings.kpi.endDate")}</Label>
              <Input
                type="date"
                value={periodEnd}
                onChange={(e) => setPeriodEnd(e.target.value)}
                required
              />
            </div>
          </div>
          <div className="space-y-1 md:col-span-2">
            <Label className="text-xs">{t("settings.kpi.notes")}</Label>
            <Input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={1024}
              placeholder={t("settings.kpi.notesPlaceholder")}
            />
          </div>
          <Button
            type="submit"
            disabled={create.isPending}
            className="md:col-span-2"
          >
            {create.isPending
              ? t("settings.common.saving")
              : t("settings.kpi.addGoal")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function _todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function _endOfMonthIso(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);
}
