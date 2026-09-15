"use client";

import { Suspense, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, Plus, Save, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Choice, ErrorMessage, Field, Loading, Workspace } from "@/components/intelligence/fields";
import {
  downloadIntelligence,
  INTELLIGENCE_API,
  useIntelligenceQuery,
  useIntelligenceTenant,
  useIntelligenceUrl,
} from "@/hooks/use-intelligence";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { useTranslation } from "@/lib/i18n/use-translation";
import { apiRequest } from "@/lib/api-client";
import type {
  CustomerList,
  CustomerProfile,
  CustomerRecord,
  RiskBand,
} from "@/lib/intelligence-types";

const bands: RiskBand[] = ["critical", "high", "watch", "low", "unknown", "inactive"];
const bandStyles: Record<RiskBand, string> = {
  critical: "text-red-700 dark:text-red-400",
  high: "text-amber-700 dark:text-amber-400",
  watch: "text-sky-700 dark:text-sky-400",
  low: "text-emerald-700 dark:text-emerald-400",
  unknown: "text-muted-foreground",
  inactive: "text-muted-foreground",
};
function newCustomer(): CustomerProfile {
  return {
    external_id: "",
    name: "",
    segment: "",
    source: "",
    observed_on: "",
    lifecycle: "active",
    last_activity_on: null,
    expected_activity_days: null,
    orders_current_30d: null,
    orders_previous_30d: null,
    usage_current_30d: null,
    usage_previous_30d: null,
    overdue_invoices: null,
    cancellation_requested: null,
    renewal_on: null,
    annual_revenue: null,
    currency: null,
    owner: "",
    next_action: "",
    follow_up_on: null,
    outcome: "open",
  };
}
export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <TenantChurn />
    </Suspense>
  );
}
function TenantChurn() {
  const tenant = useIntelligenceTenant();
  return <ChurnPage key={tenant} />;
}
function ChurnPage() {
  const { t } = useTranslation();
  const { canWrite } = useRoleFlags();
  const tenant = useIntelligenceTenant();
  const qc = useQueryClient();
  const { params, change } = useIntelligenceUrl();
  const search = params.get("search") ?? "";
  const band = bands.includes(params.get("band") as RiskBand) ? params.get("band")! : "all";
  const rawPage = Number(params.get("page") ?? "1");
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const query = useIntelligenceQuery<CustomerList>(
    `/customers?${new URLSearchParams({ search, band, page: String(page) })}`,
  );
  const [editing, setEditing] = useState<CustomerRecord | "new" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [importing, setImporting] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  async function importFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setNotice("");
    setImporting(true);
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error("CSV: max 5 MiB");
      const body = new FormData();
      body.append("file", file);
      const result = await apiRequest<{ imported: number }>(INTELLIGENCE_API + "/customer-import", {
        method: "POST",
        body,
      });
      setNotice(`${t("intel.imported")}: ${result.imported}`);
      await qc.invalidateQueries({ queryKey: ["intelligence", tenant] });
    } catch (cause) {
      setError(cause);
    } finally {
      setImporting(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  return (
    <Workspace
      title={t("intel.churn")}
      actions={
        canWrite && (
          <>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              aria-label={t("intel.import")}
              onChange={(event) => void importFile(event.target.files?.[0])}
            />
            <Button
              variant="outline"
              title={t("intel.template")}
              aria-label={t("intel.template")}
              onClick={() =>
                downloadIntelligence("/customer-import/template", "imga-customers.csv").catch(
                  setError,
                )
              }
            >
              <Download />
            </Button>
            <Button
              variant="outline"
              disabled={importing}
              onClick={() => fileInput.current?.click()}
            >
              <Upload />
              {t("intel.import")}
            </Button>
            <Button onClick={() => setEditing("new")}>
              <Plus />
              {t("intel.newCustomer")}
            </Button>
          </>
        )
      }
    >
      <ErrorMessage error={error || query.error} />
      {notice && (
        <p role="status" className="text-sm text-emerald-700">
          {notice}
        </p>
      )}
      <p className="text-muted-foreground text-sm">{t("intel.rules")}</p>
      <div className="grid grid-cols-3 gap-4 border-y py-4 lg:grid-cols-6">
        {bands.map((value) => (
          <div key={value}>
            <p className={`text-sm ${bandStyles[value]}`}>{t(`intel.${value}`)}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {query.data?.counts[value] ?? 0}
            </p>
          </div>
        ))}
      </div>
      <div className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_200px]">
        <Field
          label={t("intel.search")}
          value={search}
          maxLength={128}
          onChange={(value) => change({ search: value, page: "" }, true)}
        />
        <Choice
          label={t("intel.band")}
          value={band}
          options={["all", ...bands].map((value) => ({ value, label: t(`intel.${value}`) }))}
          onChange={(value) => change({ band: value === "all" ? "" : value, page: "" })}
        />
      </div>
      {query.isLoading ? (
        <Loading />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead>
              <tr className="text-muted-foreground border-b">
                {["name", "riskScore", "dataStatus", "owner", "followUp", "outcome"].map((key) => (
                  <th key={key} scope="col" className="px-2 py-3 font-medium">
                    {t(`intel.${key}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {query.data?.items.map((item) => (
                <tr key={item.profile.external_id} className="hover:bg-muted/40 border-b">
                  <td className="max-w-64 px-2 py-3">
                    <button
                      className="w-full text-left font-medium break-words underline-offset-4 hover:underline"
                      dir="auto"
                      onClick={() => setEditing(item)}
                    >
                      {item.profile.name}
                    </button>
                    <p className="text-muted-foreground text-xs break-all">
                      {item.profile.external_id} · {item.profile.segment}
                    </p>
                  </td>
                  <td className={`px-2 py-3 ${bandStyles[item.risk.band]}`}>
                    <strong>{item.risk.score ?? "-"}</strong>
                    <p className="text-xs">{t(`intel.${item.risk.band}`)}</p>
                  </td>
                  <td className="px-2 py-3">
                    {t(`intel.${item.risk.data_status}`)}
                    <p className="text-muted-foreground text-xs">{item.profile.observed_on}</p>
                  </td>
                  <td className="max-w-48 px-2 py-3 break-words">{item.profile.owner || "-"}</td>
                  <td className="px-2 py-3">{item.profile.follow_up_on || "-"}</td>
                  <td className="px-2 py-3">{t(`intel.${item.profile.outcome}`)}</td>
                </tr>
              ))}
              {!query.data?.items.length && (
                <tr>
                  <td colSpan={6} className="text-muted-foreground py-12 text-center">
                    {t("intel.empty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <footer className="text-muted-foreground flex flex-wrap items-center justify-between gap-3 text-sm">
        <span>
          {t("intel.capacity")}: {query.data?.account_count ?? 0} / {query.data?.capacity ?? 5000}
        </span>
        <div className="flex items-center gap-3">
          <Button
            size="icon"
            variant="outline"
            aria-label={t("intel.previous")}
            title={t("intel.previous")}
            disabled={page <= 1}
            onClick={() => change({ page: String(page - 1) })}
          >
            <ChevronLeft />
          </Button>
          <span>
            {page} / {Math.max(1, Math.ceil((query.data?.total ?? 0) / 25))}
          </span>
          <Button
            size="icon"
            variant="outline"
            aria-label={t("intel.next")}
            title={t("intel.next")}
            disabled={!query.data || page * 25 >= query.data.total}
            onClick={() => change({ page: String(page + 1) })}
          >
            <ChevronRight />
          </Button>
        </div>
      </footer>
      {editing && (
        <CustomerEditor
          key={editing === "new" ? "new" : editing.profile.external_id}
          initial={editing === "new" ? null : editing}
          close={() => setEditing(null)}
        />
      )}
    </Workspace>
  );
}
function CustomerEditor({ initial, close }: { initial: CustomerRecord | null; close: () => void }) {
  const { t } = useTranslation();
  const { canWrite, isAdmin } = useRoleFlags();
  const tenant = useIntelligenceTenant();
  const qc = useQueryClient();
  const [profile, setProfile] = useState(initial?.profile ?? newCustomer);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const { params, change } = useIntelligenceUrl();
  const cursor = Number(params.get("customer_history_before"));
  const before =
    params.get("history_customer") === initial?.profile.external_id &&
    Number.isSafeInteger(cursor) &&
    cursor > 0
      ? cursor
      : null;
  const setBefore = (value: number | null) =>
    change({
      history_customer: value ? (initial?.profile.external_id ?? "") : "",
      customer_history_before: value ? String(value) : "",
    });
  const history = useIntelligenceQuery<CustomerRecord[]>(
    `/customers/${encodeURIComponent(initial?.profile.external_id ?? "")}/history${before ? `?before=${before}` : ""}`,
    !!initial && historyOpen,
  );
  const dirty = JSON.stringify(profile) !== JSON.stringify(initial?.profile ?? newCustomer());
  function patch(values: Partial<CustomerProfile>) {
    setProfile({ ...profile, ...values });
  }
  function requestClose() {
    if (!busy && (!dirty || window.confirm(t("intel.discard")))) close();
  }
  async function persist(remove = false) {
    if (remove && !window.confirm(t("intel.deleteConfirm"))) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`${INTELLIGENCE_API}/customers/${encodeURIComponent(profile.external_id)}`, {
        method: remove ? "DELETE" : "PUT",
        body: remove ? undefined : { expected_revision: initial?.revision ?? 0, profile },
      });
      await qc.invalidateQueries({ queryKey: ["intelligence", tenant] });
      close();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  const numericFields = [
    { key: "expected_activity_days", label: "expectedDays" },
    { key: "orders_current_30d", label: "ordersCurrent" },
    { key: "orders_previous_30d", label: "ordersPrevious" },
    { key: "usage_current_30d", label: "usageCurrent" },
    { key: "usage_previous_30d", label: "usagePrevious" },
    { key: "overdue_invoices", label: "overdue" },
  ] as const;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) requestClose();
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-lg sm:max-w-4xl">
        <DialogTitle>{initial ? initial.profile.name : t("intel.newCustomer")}</DialogTitle>
        <DialogDescription>{t("intel.rules")}</DialogDescription>
        <ErrorMessage error={error} />
        {initial && (
          <section className="space-y-2 border-y py-3">
            <div className="flex flex-wrap items-center gap-3">
              <strong className={bandStyles[initial.risk.band]}>
                {initial.risk.score ?? "-"} / 100 · {t(`intel.${initial.risk.band}`)}
              </strong>
              <span>{t(`intel.${initial.risk.data_status}`)}</span>
              <span className="text-muted-foreground">{initial.risk.as_of}</span>
            </div>
            <h3 className="font-medium">{t("intel.signals")}</h3>
            {!initial.risk.signals.length && <p>{t("intel.noSignals")}</p>}
            {initial.risk.signals.map((signal) => (
              <div key={signal.code} className="border-l-2 pl-3">
                <p dir="auto">
                  +{signal.points}: {signal.evidence}
                </p>
                <p dir="auto" className="text-muted-foreground">
                  {signal.recommendation}
                </p>
              </div>
            ))}
            {initial.risk.missing.length > 0 && (
              <p className="break-words">
                {t("intel.missing")}:{" "}
                {initial.risk.missing.map((key) => t(`intel.${key}`)).join(", ")}
              </p>
            )}
          </section>
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void persist();
          }}
          className="space-y-5"
        >
          <fieldset
            disabled={!canWrite || busy}
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          >
            <Field
              label={t("intel.externalId")}
              value={profile.external_id}
              required
              disabled={!!initial}
              maxLength={128}
              onChange={(external_id) => patch({ external_id })}
            />
            <Field
              label={t("intel.name")}
              value={profile.name}
              required
              maxLength={160}
              onChange={(name) => patch({ name })}
            />
            <Field
              label={t("intel.segment")}
              value={profile.segment}
              maxLength={128}
              onChange={(segment) => patch({ segment })}
            />
            <Field
              label={t("intel.source")}
              value={profile.source}
              required
              maxLength={160}
              onChange={(source) => patch({ source })}
            />
            <Field
              label={t("intel.observedOn")}
              value={profile.observed_on}
              required
              type="date"
              onChange={(observed_on) => patch({ observed_on })}
            />
            <Choice
              label={t("intel.lifecycle")}
              value={profile.lifecycle}
              options={["active", "paused", "churned"].map((value) => ({
                value,
                label: t(`intel.${value}`),
              }))}
              onChange={(value) => patch({ lifecycle: value as CustomerProfile["lifecycle"] })}
            />
            <Field
              label={t("intel.lastActivity")}
              value={profile.last_activity_on}
              type="date"
              onChange={(last_activity_on) => patch({ last_activity_on: last_activity_on || null })}
            />
            {numericFields.map(({ key, label }) => (
              <Field
                key={key}
                label={t(`intel.${label}`)}
                value={profile[key]}
                type="number"
                onChange={(value) => patch({ [key]: value === "" ? null : Number(value) })}
              />
            ))}
            <Choice
              label={t("intel.cancellation")}
              value={
                profile.cancellation_requested === null
                  ? "unknown"
                  : String(profile.cancellation_requested)
              }
              options={[
                { value: "unknown", label: t("intel.none") },
                { value: "true", label: t("intel.yes") },
                { value: "false", label: t("intel.no") },
              ]}
              onChange={(value) =>
                patch({ cancellation_requested: value === "unknown" ? null : value === "true" })
              }
            />
            <Field
              label={t("intel.renewal")}
              value={profile.renewal_on}
              type="date"
              onChange={(renewal_on) => patch({ renewal_on: renewal_on || null })}
            />
            <Field
              label={t("intel.revenue")}
              value={profile.annual_revenue}
              type="number"
              onChange={(annual_revenue) => patch({ annual_revenue: annual_revenue || null })}
            />
            <Choice
              label={t("intel.currency")}
              value={profile.currency ?? ""}
              options={[
                { value: "", label: t("intel.none") },
                ...["SAR", "AED", "USD", "EUR", "TRY"].map((value) => ({ value, label: value })),
              ]}
              onChange={(currency) => patch({ currency: currency || null })}
            />
            <Field
              label={t("intel.owner")}
              value={profile.owner}
              maxLength={160}
              onChange={(owner) => patch({ owner })}
            />
            <Field
              label={t("intel.followUp")}
              value={profile.follow_up_on}
              type="date"
              onChange={(follow_up_on) => patch({ follow_up_on: follow_up_on || null })}
            />
            <Choice
              label={t("intel.outcome")}
              value={profile.outcome}
              options={["open", "contacted", "retained", "lost", "monitoring"].map((value) => ({
                value,
                label: t(`intel.${value}`),
              }))}
              onChange={(value) => patch({ outcome: value as CustomerProfile["outcome"] })}
            />
            <div className="sm:col-span-2 lg:col-span-3">
              <Field
                label={t("intel.nextAction")}
                value={profile.next_action}
                multiline
                maxLength={2000}
                onChange={(next_action) => patch({ next_action })}
              />
            </div>
          </fieldset>
          <div className="flex flex-wrap justify-between gap-3 border-t pt-4">
            <div>
              {isAdmin && initial && (
                <Button
                  type="button"
                  variant="destructive"
                  disabled={busy}
                  onClick={() => persist(true)}
                >
                  <Trash2 />
                  {t("intel.remove")}
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="outline" disabled={busy} onClick={requestClose}>
                {t("intel.close")}
              </Button>
              {canWrite && (
                <Button type="submit" disabled={busy}>
                  <Save />
                  {t("intel.saveCustomer")}
                </Button>
              )}
            </div>
          </div>
        </form>
        {initial && (
          <details onToggle={(event) => setHistoryOpen(event.currentTarget.open)}>
            <summary className="cursor-pointer font-medium">{t("intel.history")}</summary>
            <ErrorMessage error={history.error} />
            {history.isFetching && <Loading />}
            {history.data?.map((record) => (
              <div key={record.revision} className="border-b py-2">
                <p>
                  {t("intel.revision")} {record.revision} · {record.profile.observed_on} ·{" "}
                  {record.risk.score ?? "-"}/100 · {t(`intel.${record.risk.band}`)}
                </p>
                <p>
                  {record.profile.source} · {record.profile.owner} ·{" "}
                  {t(`intel.${record.profile.outcome}`)}
                </p>
                <p dir="auto">{record.profile.next_action}</p>
              </div>
            ))}
            <div className="flex gap-2 pt-2">
              {before && (
                <Button variant="outline" onClick={() => setBefore(null)}>
                  {t("intel.current")}
                </Button>
              )}
              {history.data?.length === 20 && (
                <Button
                  variant="outline"
                  onClick={() => setBefore(history.data?.at(-1)?.revision ?? null)}
                >
                  {t("intel.older")}
                </Button>
              )}
            </div>
          </details>
        )}
      </DialogContent>
    </Dialog>
  );
}
