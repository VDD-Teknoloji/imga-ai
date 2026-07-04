"use client";

// Sprint 9.2 D — /settings/scheduled-briefings.
//
// One row per active schedule, plus an inline "Yeni schedule" form.
// Each row exposes enabled-toggle + send-now + delete; the
// last_run_status badge surfaces the audit at a glance ("son çalışma:
// dün 09:00, başarılı").

import {
  CalendarClock,
  CheckCircle2,
  Loader2,
  Send,
  Trash2,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type BriefingSchedule,
  type SchedulePeriod,
  useBriefingSchedules,
  useCreateBriefingSchedule,
  useDeleteBriefingSchedule,
  useRunBriefingScheduleNow,
  useUpdateBriefingSchedule,
} from "@/hooks/use-briefing-schedules";
import { formatApiErrorMessage } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

const WEEKDAY_KEYS = [
  "settings.briefings.weekday.mon",
  "settings.briefings.weekday.tue",
  "settings.briefings.weekday.wed",
  "settings.briefings.weekday.thu",
  "settings.briefings.weekday.fri",
  "settings.briefings.weekday.sat",
  "settings.briefings.weekday.sun",
] as const;

export default function ScheduledBriefingsPage() {
  return (
    <RequireRole level="admin">
      <ScheduledBriefingsPageInner />
    </RequireRole>
  );
}

function ScheduledBriefingsPageInner() {
  const list = useBriefingSchedules();
  const { t } = useTranslation();

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <CalendarClock className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("settings.briefings.title")}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t("settings.briefings.subtitle")}
          </p>
        </div>
      </header>

      <CreateForm />

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : list.isError ? (
        <p className="text-destructive text-sm">
          {t("settings.briefings.loadError")}
        </p>
      ) : !list.data || list.data.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground p-6 text-center text-sm">
            {t("settings.briefings.empty")}
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-2">
          {list.data.map((s) => (
            <ScheduleRow key={s.id} schedule={s} />
          ))}
        </ul>
      )}
    </main>
  );
}

function ScheduleRow({ schedule }: { schedule: BriefingSchedule }) {
  const update = useUpdateBriefingSchedule();
  const del = useDeleteBriefingSchedule();
  const runNow = useRunBriefingScheduleNow();
  const { t } = useTranslation();

  const weekdayKey =
    schedule.period === "weekly"
      ? WEEKDAY_KEYS[schedule.schedule_day]
      : undefined;
  const dayLabel =
    schedule.period === "weekly"
      ? weekdayKey
        ? t(weekdayKey)
        : t("settings.briefings.dayFallback", { n: schedule.schedule_day })
      : t("settings.briefings.dayOfMonth", { n: schedule.schedule_day });
  const hourLabel = `${schedule.schedule_hour.toString().padStart(2, "0")}:00`;

  return (
    <li className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-3">
      <div className="flex-1 space-y-0.5">
        <p className="text-sm font-medium">
          {schedule.period === "weekly"
            ? t("settings.briefings.weekly")
            : t("settings.briefings.monthly")}{" "}
          · {dayLabel} · {hourLabel} ({schedule.timezone})
        </p>
        <p className="text-muted-foreground text-xs">
          {t("settings.briefings.next")}{" "}
          {new Date(schedule.next_run_at).toLocaleString("tr-TR")}
          {schedule.last_run_at && (
            <>
              {" · "}
              {t("settings.briefings.last")}{" "}
              {new Date(schedule.last_run_at).toLocaleString("tr-TR")}
            </>
          )}
        </p>
        <p className="text-muted-foreground text-xs">
          {t("settings.briefings.recipientsUsers", {
            n: schedule.recipients.length,
          })}
          {schedule.email_recipients.length > 0 && (
            <>
              {" "}
              {t("settings.briefings.recipientsEmails", {
                n: schedule.email_recipients.length,
              })}
            </>
          )}
        </p>
      </div>
      <StatusBadge status={schedule.last_run_status} />
      {!schedule.enabled && (
        <Badge
          variant="outline"
          className="border-zinc-400 bg-zinc-100 text-xs text-zinc-700"
        >
          {t("settings.common.disabled")}
        </Badge>
      )}
      <Button
        size="sm"
        variant="ghost"
        onClick={() =>
          update.mutate(
            { id: schedule.id, body: { enabled: !schedule.enabled } },
            {
              onSuccess: () =>
                toast.success(
                  !schedule.enabled
                    ? t("settings.briefings.enabled")
                    : t("settings.briefings.paused"),
                ),
              onError: (err) => toast.error(formatApiErrorMessage(err)),
            },
          )
        }
        disabled={update.isPending}
      >
        {schedule.enabled
          ? t("settings.briefings.pause")
          : t("settings.briefings.enable")}
      </Button>
      <Button
        size="sm"
        onClick={() =>
          // Sprint 9.4.2 hotfix — run-now's route handler catches a
          // failed briefing generation, records ``last_run_status =
          // 'failed'`` on the schedule, and returns 200 with the
          // updated schedule in the body. HTTP 200 alone is therefore
          // not a success signal; the actual outcome lives on the
          // response's ``last_run_status``. Pre-fix every run popped a
          // green "Brifing üretildi" toast even when the LLM had 504'd.
          runNow.mutate(schedule.id, {
            onSuccess: (updated) => {
              if (updated.last_run_status === "success") {
                toast.success(t("settings.briefings.generated"));
              } else {
                toast.error(
                  t("settings.briefings.generateFailed", {
                    error:
                      updated.last_run_error ||
                      t("settings.briefings.unknownError"),
                  }),
                );
              }
            },
            onError: (err) => toast.error(formatApiErrorMessage(err)),
          })
        }
        disabled={runNow.isPending}
        className="gap-1"
      >
        {runNow.isPending ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : (
          <Send className="size-3.5" aria-hidden />
        )}
        {t("settings.briefings.sendNow")}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          if (!confirm(t("settings.briefings.deleteConfirm"))) return;
          del.mutate(schedule.id, {
            onSuccess: () => toast.success(t("settings.briefings.deleted")),
            onError: (err) => toast.error(formatApiErrorMessage(err)),
          });
        }}
        disabled={del.isPending}
        className="gap-1 text-red-700 hover:text-red-900"
      >
        <Trash2 className="size-3.5" aria-hidden /> {t("settings.common.delete")}
      </Button>
    </li>
  );
}

function StatusBadge({
  status,
}: {
  status: BriefingSchedule["last_run_status"];
}) {
  const { t } = useTranslation();
  if (status === "success") {
    return (
      <Badge className="bg-emerald-100 text-emerald-900 hover:bg-emerald-100">
        <CheckCircle2 className="mr-1 size-3" /> {t("settings.briefings.statusOk")}
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge className="bg-red-100 text-red-900 hover:bg-red-100">
        <XCircle className="mr-1 size-3" /> {t("settings.briefings.statusFailed")}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-xs">
      {t("settings.briefings.statusNever")}
    </Badge>
  );
}

function CreateForm() {
  const create = useCreateBriefingSchedule();
  const { t } = useTranslation();
  const [period, setPeriod] = useState<SchedulePeriod>("monthly");
  const [day, setDay] = useState<number>(1);
  const [hour, setHour] = useState<number>(9);
  const [emailsRaw, setEmailsRaw] = useState<string>("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const emails = emailsRaw
      .split(/[,\n;]/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    create.mutate(
      {
        period,
        schedule_day: day,
        schedule_hour: hour,
        email_recipients: emails,
        recipients: [],
        enabled: true,
      },
      {
        onSuccess: () => {
          toast.success(t("settings.briefings.added"));
          setEmailsRaw("");
        },
        onError: (err) => toast.error(formatApiErrorMessage(err)),
      },
    );
  }

  const dayOptions =
    period === "weekly"
      ? WEEKDAY_KEYS.map((key, i) => ({ value: i, label: t(key) }))
      : Array.from({ length: 28 }, (_, i) => ({
          value: i + 1,
          label: `${i + 1}.`,
        }));

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">
          {t("settings.briefings.newSchedule")}
        </h2>
        <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1">
            <Label className="text-xs">{t("settings.briefings.periodLabel")}</Label>
            <select
              value={period}
              onChange={(e) => {
                const next = e.target.value as SchedulePeriod;
                setPeriod(next);
                setDay(next === "weekly" ? 0 : 1);
              }}
              className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm"
            >
              <option value="monthly">{t("settings.briefings.monthly")}</option>
              <option value="weekly">{t("settings.briefings.weekly")}</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("settings.briefings.dayLabel")}</Label>
            <select
              value={day}
              onChange={(e) => setDay(Number(e.target.value))}
              className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm"
            >
              {dayOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("settings.briefings.hourLabel")}</Label>
            <Input
              type="number"
              min={0}
              max={23}
              value={hour}
              onChange={(e) => setHour(Number(e.target.value))}
            />
          </div>
          <div className="md:col-span-3">
            <Label className="text-xs">
              {t("settings.briefings.emailRecipients")}
            </Label>
            <Input
              value={emailsRaw}
              onChange={(e) => setEmailsRaw(e.target.value)}
              placeholder="ceo@firma.com, board@firma.com"
            />
            <p className="text-muted-foreground mt-1 text-[10px]">
              {t("settings.briefings.smtpHelp")}
            </p>
          </div>
          <Button
            type="submit"
            disabled={create.isPending}
            className="md:col-span-3"
          >
            {create.isPending
              ? t("settings.common.saving")
              : t("settings.briefings.addSchedule")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
