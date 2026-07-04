"use client";

// Sprint 9.3 C — /admin/decision-audit timeline.
// Sprint 9.4 H — Suspense wrapper + Path B URL-state mirror so the
// decision_type filter survives F5 + back/forward + share-link.

import { History, Loader2 } from "lucide-react";
import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { RequireRole } from "@/components/auth/require-role";
import { Badge } from "@/components/ui/badge";
import { type DecisionAuditRow, useDecisionAuditList } from "@/hooks/use-decision-audit";
import { useTranslation } from "@/lib/i18n/use-translation";

const DECISION_LABEL_KEYS: Record<string, string> = {
  briefing_acknowledged: "admin.decisionAudit.type.briefingAcknowledged",
  briefing_dismissed: "admin.decisionAudit.type.briefingDismissed",
  strategic_report_approved: "admin.decisionAudit.type.strategicReportApproved",
  strategic_report_rejected: "admin.decisionAudit.type.strategicReportRejected",
  action_item_assigned: "admin.decisionAudit.type.actionItemAssigned",
  action_item_priority_changed: "admin.decisionAudit.type.actionItemPriorityChanged",
  sla_rule_changed: "admin.decisionAudit.type.slaRuleChanged",
  kpi_goal_set: "admin.decisionAudit.type.kpiGoalSet",
  webhook_dispatched_manually: "admin.decisionAudit.type.webhookDispatchedManually",
  tenant_setting_changed: "admin.decisionAudit.type.tenantSettingChanged",
  prompt_template_overridden: "admin.decisionAudit.type.promptTemplateOverridden",
};

export default function DecisionAuditPage() {
  return (
    <RequireRole level="admin">
      <Suspense fallback={<PageSkeleton />}>
        <DecisionAuditPageInner />
      </Suspense>
    </RequireRole>
  );
}

function PageSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:p-8">
      <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
    </main>
  );
}

function DecisionAuditPageInner() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Path B mirror — local state seeded from URL, kept in sync via the
  // useEffect below so back/forward + deep-link land on the right
  // filter without a flicker.
  const [decisionType, setDecisionType] = useState<string>(
    () => searchParams.get("decision_type") ?? "",
  );

  useEffect(() => {
    const fromUrl = searchParams.get("decision_type") ?? "";
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDecisionType((prev) => (prev === fromUrl ? prev : fromUrl));
  }, [searchParams]);

  const updateFilter = useCallback(
    (next: string) => {
      setDecisionType(next);
      const params = new URLSearchParams(searchParams);
      if (next === "") {
        params.delete("decision_type");
      } else {
        params.set("decision_type", next);
      }
      const qs = params.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname);
    },
    [pathname, router, searchParams],
  );

  const list = useDecisionAuditList({
    decision_type: decisionType || undefined,
    limit: 200,
  });

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <History className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("admin.decisionAudit.title")}
          </h1>
          <p className="text-muted-foreground text-sm">{t("admin.decisionAudit.subtitle")}</p>
        </div>
      </header>

      <div className="bg-card flex items-center gap-3 rounded-lg border p-3">
        <select
          value={decisionType}
          onChange={(e) => updateFilter(e.target.value)}
          className="border-input bg-background rounded-md border px-2 py-1 text-sm"
        >
          <option value="">{t("admin.decisionAudit.allTypes")}</option>
          {Object.entries(DECISION_LABEL_KEYS).map(([k, keyName]) => (
            <option key={k} value={k}>
              {t(keyName)}
            </option>
          ))}
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
        <ol className="space-y-2">
          {list.data.items.map((row) => (
            <DecisionRow key={row.id} row={row} />
          ))}
        </ol>
      )}
    </main>
  );
}

function DecisionRow({ row }: { row: DecisionAuditRow }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const labelKey = DECISION_LABEL_KEYS[row.decision_type];
  const label = labelKey ? t(labelKey) : row.decision_type;
  return (
    <li className="bg-card rounded-lg border p-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-wrap items-center gap-2 text-left"
      >
        <span className="text-sm font-medium">{label}</span>
        <Badge variant="outline" className="text-xs">
          {row.related_entity_type}
        </Badge>
        {row.actor_user_id && (
          <span className="text-muted-foreground text-xs">
            user: {row.actor_user_id.slice(0, 8)}…
          </span>
        )}
        <span className="text-muted-foreground ml-auto text-xs tabular-nums">
          {new Date(row.created_at).toLocaleString("tr-TR")}
        </span>
      </button>
      {expanded && (
        <div className="mt-3 space-y-2 border-t pt-3 text-xs">
          {row.rationale && (
            <p className="bg-muted rounded p-2">
              <strong>{t("admin.decisionAudit.rationale")}</strong> {row.rationale}
            </p>
          )}
          {Object.keys(row.payload).length > 0 && (
            <pre className="bg-muted overflow-x-auto rounded p-2 font-mono">
              {JSON.stringify(row.payload, null, 2)}
            </pre>
          )}
          {row.request_id && <p className="text-muted-foreground">req={row.request_id}</p>}
        </div>
      )}
    </li>
  );
}
