"use client";

// Sprint 9.0.5-B B — Bekleyen Bildirimler (pending webhooks).
//
// When a tenant flips ``sla_webhook_dispatch_mode`` to ``manual``,
// every SLA breach the engine matches lands in
// ``pending_webhook_events`` (instead of httpx.post-ing live to
// Slack/Teams). This page is the operator's queue: pending rows
// with Dispatch + Cancel buttons, dispatched/failed/dismissed rows
// surface in filtered tabs for an audit trail.
//
// URL state (Path B): ``?status=pending|sent|failed|dismissed|all
// &page=N``. F5 / back / copy-paste preserve filter + page.
// Polling 30s on the active filter.

import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Send,
  ShieldAlert,
  Trash2,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  type PendingWebhookEvent,
  type PendingWebhookStatus,
  useCancelPendingWebhook,
  useDispatchPendingWebhook,
  useTenantPendingWebhooks,
} from "@/hooks/use-pending-webhooks";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

const STATUS_TABS: ReadonlyArray<{
  value: PendingWebhookStatus | "all";
  labelKey: string;
}> = [
  { value: "pending", labelKey: "admin.pendingNotifications.tab.pending" },
  { value: "sent", labelKey: "admin.pendingNotifications.tab.sent" },
  { value: "failed", labelKey: "admin.pendingNotifications.tab.failed" },
  { value: "dismissed", labelKey: "admin.pendingNotifications.tab.dismissed" },
  { value: "all", labelKey: "admin.pendingNotifications.tab.all" },
];

const PAGE_SIZE = 25;

export default function PendingWebhooksPage() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <Content />
    </Suspense>
  );
}

function HeaderSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-center gap-2">
        <ShieldAlert className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">{t("admin.pendingNotifications.title")}</h1>
          <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
        </div>
      </header>
    </main>
  );
}

function Content() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const initialStatus = (searchParams.get("status") ?? "pending") as PendingWebhookStatus | "all";
  const initialPage = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);

  const [statusTab, setStatusTabState] = useState<PendingWebhookStatus | "all">(initialStatus);
  const [page, setPageState] = useState<number>(initialPage);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlStatus = (searchParams.get("status") ?? "pending") as PendingWebhookStatus | "all";
    setStatusTabState((prev) => (prev === urlStatus ? prev : urlStatus));
    const urlPage = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);
    setPageState((prev) => (prev === urlPage ? prev : urlPage));
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParams(updates: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v === null || v === "") params.delete(k);
      else params.set(k, v);
    }
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const list = useTenantPendingWebhooks({
    status: statusTab,
    page,
    pageSize: PAGE_SIZE,
  });

  const events = list.data?.events ?? [];
  const total = list.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <ShieldAlert className="text-primary mt-1 size-6" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
              {t("admin.pendingNotifications.title")}
            </h1>
            <p className="text-muted-foreground text-sm">
              {t("admin.pendingNotifications.subtitle")}
            </p>
          </div>
        </div>
        <Link
          href="/settings/sla-rules"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" /> {t("admin.pendingNotifications.slaRules")}
        </Link>
      </header>

      <div className="bg-card flex flex-wrap items-center gap-2 rounded-lg border p-2">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => {
              setStatusTabState(tab.value);
              setPageState(1);
              pushParams({
                status: tab.value === "pending" ? null : tab.value,
                page: null,
              });
            }}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              statusTab === tab.value ? "bg-primary text-primary-foreground" : "hover:bg-muted"
            }`}
          >
            {t(tab.labelKey)}
          </button>
        ))}
        <span className="text-muted-foreground ml-auto text-xs">
          {t("admin.pendingNotifications.total", { n: total })}
        </span>
      </div>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : list.isError ? (
        <Card>
          <CardContent className="flex items-center gap-2 p-6 text-sm text-red-600">
            <AlertTriangle className="size-4" /> {t("admin.common.listError")}
          </CardContent>
        </Card>
      ) : events.length === 0 ? (
        <EmptyState statusTab={statusTab} />
      ) : (
        <ul className="space-y-2">
          {events.map((evt) => (
            <PendingRow key={evt.id} event={evt} />
          ))}
        </ul>
      )}

      {totalPages > 1 && (
        <Pagination
          page={page}
          totalPages={totalPages}
          onChange={(next) => {
            setPageState(next);
            pushParams({ page: next === 1 ? null : String(next) });
          }}
        />
      )}
    </main>
  );
}

function PendingRow({ event }: { event: PendingWebhookEvent }) {
  const { t } = useTranslation();
  const dispatch = useDispatchPendingWebhook();
  const cancel = useCancelPendingWebhook();
  const isPending = event.status === "pending";
  const isFailed = event.status === "failed";

  const target =
    event.webhook_target === "slack"
      ? "Slack"
      : event.webhook_target === "teams"
        ? "Teams"
        : event.webhook_target;
  const ruleName =
    typeof event.payload?.rule_name === "string"
      ? event.payload.rule_name
      : t("admin.pendingNotifications.noRuleName");
  const reviewText =
    typeof event.payload?.review_text === "string" ? event.payload.review_text : null;

  const onDispatch = () => {
    dispatch.mutate(event.id, {
      onSuccess: () => toast.success(t("admin.pendingNotifications.toast.dispatched")),
      onError: (err) =>
        toast.error(
          err instanceof ApiError
            ? err.detail
            : t("admin.pendingNotifications.toast.dispatchFailed"),
        ),
    });
  };
  const onCancel = () => {
    cancel.mutate(event.id, {
      onSuccess: () => toast.success(t("admin.pendingNotifications.toast.cancelled")),
      onError: (err) =>
        toast.error(
          err instanceof ApiError ? err.detail : t("admin.pendingNotifications.toast.cancelFailed"),
        ),
    });
  };

  return (
    <li className="bg-card flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{ruleName}</span>
          <Badge variant="outline" className="text-xs">
            {target}
          </Badge>
          <StatusBadge status={event.status} />
          {event.channel && (
            <span className="text-muted-foreground text-xs">· #{event.channel}</span>
          )}
        </div>
        {reviewText && <p className="text-muted-foreground line-clamp-2 text-xs">{reviewText}</p>}
        <p className="text-muted-foreground text-xs">
          {new Date(event.created_at).toLocaleString("tr-TR")}
          {event.retry_count > 0 &&
            ` · ${t("admin.pendingNotifications.retries", {
              n: event.retry_count,
            })}`}
        </p>
        {isFailed && event.last_error && (
          <p className="line-clamp-2 text-xs text-red-600">{event.last_error}</p>
        )}
      </div>
      {(isPending || isFailed) && (
        <div className="flex flex-wrap gap-2 sm:flex-col sm:items-end">
          <Button size="sm" onClick={onDispatch} disabled={dispatch.isPending} className="gap-1">
            {dispatch.isPending ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <Send className="size-3.5" aria-hidden />
            )}
            {t("admin.pendingNotifications.dispatch")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onCancel}
            disabled={cancel.isPending}
            className="gap-1"
          >
            <Trash2 className="size-3.5" aria-hidden />
            {t("admin.pendingNotifications.cancel")}
          </Button>
        </div>
      )}
    </li>
  );
}

function StatusBadge({ status }: { status: PendingWebhookStatus }) {
  const { t } = useTranslation();
  if (status === "pending")
    return (
      <Badge className="bg-amber-100 text-amber-900 hover:bg-amber-100">
        {t("admin.pendingNotifications.status.pending")}
      </Badge>
    );
  if (status === "sent")
    return (
      <Badge className="bg-emerald-100 text-emerald-900 hover:bg-emerald-100">
        <CheckCircle2 className="mr-1 size-3" /> {t("admin.pendingNotifications.status.sent")}
      </Badge>
    );
  if (status === "failed")
    return (
      <Badge className="bg-red-100 text-red-900 hover:bg-red-100">
        <XCircle className="mr-1 size-3" /> {t("admin.pendingNotifications.status.failed")}
      </Badge>
    );
  return (
    <Badge variant="outline" className="text-xs">
      {t("admin.pendingNotifications.status.dismissed")}
    </Badge>
  );
}

function EmptyState({ statusTab }: { statusTab: PendingWebhookStatus | "all" }) {
  const { t } = useTranslation();
  const message =
    statusTab === "pending"
      ? t("admin.pendingNotifications.empty.pending")
      : t("admin.pendingNotifications.empty.filtered");
  return (
    <div className="bg-card rounded-lg border border-dashed p-8 text-center">
      <p className="text-muted-foreground text-sm">{message}</p>
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  onChange,
}: {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChange(Math.max(1, page - 1))}
        disabled={page <= 1}
        className="gap-1"
      >
        <ChevronLeft className="size-4" /> {t("admin.pendingNotifications.prev")}
      </Button>
      <span className="text-muted-foreground text-sm">
        {t("admin.pendingNotifications.pageInfo", {
          page,
          total: totalPages,
        })}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChange(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="gap-1"
      >
        {t("admin.pendingNotifications.next")} <ChevronRight className="size-4" />
      </Button>
    </div>
  );
}
