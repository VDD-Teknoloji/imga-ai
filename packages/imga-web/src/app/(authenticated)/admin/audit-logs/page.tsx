"use client";

// C4/B2 (2026-08-20 süper-admin envanteri) — /admin/audit-logs "Denetim
// Kayıtları". audit_logs tablosu bugüne kadar yalnız yazılıyordu; bu
// sayfa ilk okuma yüzeyi — "bu kurumda kim ne yaptı" sorusuna cevap.
//
// /admin/tenants ile aynı öz-koruma deseni (isSuperAdmin). Suspense +
// Path B URL-state — bkz. docs/agent-rules/url-state-patterns.md.
// ``action`` serbest metin filtresi tek istisna: yüksek frekanslı
// yazma (her tuş vuruşu) olduğu için debounce + router.replace
// kullanır (doc'un "form input typing" istisnası); tenant/tarih/offset
// push kullanır.

import { ChevronLeft, ChevronRight, Loader2, ScrollText } from "lucide-react";
import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { DateField } from "@/components/ui/date-field";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { type AdminAuditLogItem, useAdminAuditLogs } from "@/hooks/use-admin-audit-logs";
import { useAdminTenants } from "@/hooks/use-admin-tenants";
import { useAuthStore } from "@/lib/auth-store";
import { formatFullDate } from "@/lib/date-format";
import { useTranslation } from "@/lib/i18n/use-translation";

const LIMIT = 50;
const ACTION_DEBOUNCE_MS = 400;

export default function AdminAuditLogsPage() {
  const isSuperAdmin = useAuthStore((s) => s.user?.is_super_admin ?? false);
  if (!isSuperAdmin) {
    return <ForbiddenView />;
  }
  return (
    <Suspense fallback={<PageSkeleton />}>
      <AdminAuditLogsPageInner />
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

interface PushFilters {
  tenant_id: string;
  date_from: string;
  date_to: string;
  offset: number;
}

function readPushFilters(params: URLSearchParams): PushFilters {
  return {
    tenant_id: params.get("tenant_id") ?? "",
    date_from: params.get("date_from") ?? "",
    date_to: params.get("date_to") ?? "",
    offset: Math.max(0, Number(params.get("offset") ?? "0") || 0),
  };
}

function pushFiltersEq(a: PushFilters, b: PushFilters): boolean {
  return (
    a.tenant_id === b.tenant_id &&
    a.date_from === b.date_from &&
    a.date_to === b.date_to &&
    a.offset === b.offset
  );
}

function AdminAuditLogsPageInner() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tenants = useAdminTenants();

  // Path B mirror — tenant_id/date_from/date_to/offset (push-based).
  const [filters, setFilters] = useState<PushFilters>(() =>
    readPushFilters(new URLSearchParams(searchParams.toString())),
  );
  useEffect(() => {
    const fromUrl = readPushFilters(new URLSearchParams(searchParams.toString()));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters((prev) => (pushFiltersEq(prev, fromUrl) ? prev : fromUrl));
    // INTENT: URL is source of truth; mirror onto local state on
    // navigation events (back/forward, deep-link, F5 hydration race).
  }, [searchParams]);

  // ``action`` ayrı state — debounce + replace semantiği push-based
  // filtrelerden farklı (bkz. dosya başı yorumu).
  const [actionQuery, setActionQuery] = useState<string>(() => searchParams.get("action") ?? "");
  useEffect(() => {
    const fromUrl = searchParams.get("action") ?? "";
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setActionQuery((prev) => (prev === fromUrl ? prev : fromUrl));
  }, [searchParams]);

  // Kurum/tarih değişimi: sayfayı başa al (offset=0), push (paylaşılabilir
  // + history entry).
  const applyFilters = useCallback(
    (patch: Partial<Omit<PushFilters, "offset">>) => {
      const next: PushFilters = { ...filters, ...patch, offset: 0 };
      setFilters(next);
      const params = new URLSearchParams(searchParams.toString());
      const apply = (key: string, value: string) => {
        if (value) params.set(key, value);
        else params.delete(key);
      };
      apply("tenant_id", next.tenant_id);
      apply("date_from", next.date_from);
      apply("date_to", next.date_to);
      params.delete("offset");
      const qs = params.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [filters, pathname, router, searchParams],
  );

  // Sayfalama: yalnız offset değişir, diğer filtreler korunur.
  const changeOffset = useCallback(
    (nextOffset: number) => {
      setFilters((prev) => ({ ...prev, offset: nextOffset }));
      const params = new URLSearchParams(searchParams.toString());
      if (nextOffset > 0) params.set("offset", String(nextOffset));
      else params.delete("offset");
      const qs = params.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  // Debounced action -> URL. URL->state mirror effect'i actionQuery'yi
  // önce URL değeriyle eşitler; bu effect o durumda erken çıkar (guard),
  // yalnız GERÇEK kullanıcı yazımında (actionQuery URL'den sapmışken)
  // 400ms sonra replace eder — back/forward ile "savaşmaz".
  useEffect(() => {
    const current = searchParams.get("action") ?? "";
    if (actionQuery === current) return;
    const timer = setTimeout(() => {
      const params = new URLSearchParams(searchParams.toString());
      if (actionQuery) params.set("action", actionQuery);
      else params.delete("action");
      params.delete("offset");
      setFilters((prev) => (prev.offset === 0 ? prev : { ...prev, offset: 0 }));
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    }, ACTION_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [actionQuery, searchParams, pathname, router]);

  const list = useAdminAuditLogs({
    tenant_id: filters.tenant_id || undefined,
    action: actionQuery || undefined,
    date_from: filters.date_from || undefined,
    date_to: filters.date_to || undefined,
    limit: LIMIT,
    offset: filters.offset,
  });

  const total = list.data?.total ?? 0;

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <ScrollText className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("admin.auditLogs.title")}
          </h1>
          <p className="text-muted-foreground text-sm">{t("admin.auditLogs.subtitle")}</p>
        </div>
      </header>

      <div className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <select
          value={filters.tenant_id}
          onChange={(e) => applyFilters({ tenant_id: e.target.value })}
          className="border-input bg-background rounded-md border px-2 py-1 text-sm"
        >
          <option value="">{t("admin.auditLogs.allTenants")}</option>
          {(tenants.data ?? []).map((tenant) => (
            <option key={tenant.id} value={tenant.id}>
              {tenant.name}
            </option>
          ))}
        </select>
        <Input
          value={actionQuery}
          onChange={(e) => setActionQuery(e.target.value)}
          placeholder={t("admin.auditLogs.actionPlaceholder")}
          aria-label={t("admin.auditLogs.actionPlaceholder")}
          className="w-48"
        />
        <DateField
          value={filters.date_from}
          max={filters.date_to || undefined}
          aria-label={t("admin.usage.range.fromAria")}
          onChange={(e) => applyFilters({ date_from: e.target.value })}
        />
        <span className="text-muted-foreground text-xs" aria-hidden>
          –
        </span>
        <DateField
          value={filters.date_to}
          min={filters.date_from || undefined}
          aria-label={t("admin.usage.range.toAria")}
          onChange={(e) => applyFilters({ date_to: e.target.value })}
        />
        <span className="text-muted-foreground ml-auto text-xs">
          {t("admin.common.recordCount", { n: total })}
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
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("admin.auditLogs.col.time")}</TableHead>
                <TableHead>{t("admin.auditLogs.col.tenant")}</TableHead>
                <TableHead className="hidden md:table-cell">
                  {t("admin.auditLogs.col.actor")}
                </TableHead>
                <TableHead>{t("admin.auditLogs.col.action")}</TableHead>
                <TableHead className="hidden lg:table-cell">
                  {t("admin.auditLogs.col.resource")}
                </TableHead>
                <TableHead className="hidden xl:table-cell">
                  {t("admin.auditLogs.col.ip")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.data.items.map((row) => (
                <AuditLogRow key={row.id} row={row} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <OffsetPagination
        offset={filters.offset}
        limit={LIMIT}
        total={total}
        onChange={changeOffset}
      />
    </main>
  );
}

function AuditLogRow({ row }: { row: AdminAuditLogItem }) {
  const resourceId = row.resource_id ? `${row.resource_id.slice(0, 8)}…` : null;
  return (
    <TableRow>
      <TableCell className="text-muted-foreground text-xs whitespace-nowrap tabular-nums">
        {formatFullDate(row.created_at)}
      </TableCell>
      <TableCell className="text-xs">{row.tenant_name ?? "—"}</TableCell>
      <TableCell className="text-muted-foreground hidden text-xs md:table-cell">
        {row.actor_email ?? "—"}
      </TableCell>
      <TableCell className="font-mono text-xs">{row.action}</TableCell>
      <TableCell className="text-muted-foreground hidden text-xs lg:table-cell">
        {row.resource_type}
        {resourceId ? ` · ${resourceId}` : ""}
      </TableCell>
      <TableCell className="text-muted-foreground hidden font-mono text-xs xl:table-cell">
        {row.ip_address ?? "—"}
      </TableCell>
    </TableRow>
  );
}

function OffsetPagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (next: number) => void;
}) {
  const { t } = useTranslation();
  const totalPages = Math.max(1, Math.ceil(total / limit));
  if (totalPages <= 1) return null;
  const page = Math.floor(offset / limit) + 1;
  return (
    <div className="flex items-center justify-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChange(Math.max(0, offset - limit))}
        disabled={offset <= 0}
        className="gap-1"
      >
        <ChevronLeft className="size-4" /> {t("admin.auditLogs.prev")}
      </Button>
      <span className="text-muted-foreground text-sm">
        {t("admin.auditLogs.pageInfo", { page, total: totalPages })}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChange(offset + limit)}
        disabled={offset + limit >= total}
        className="gap-1"
      >
        {t("admin.auditLogs.next")} <ChevronRight className="size-4" />
      </Button>
    </div>
  );
}
