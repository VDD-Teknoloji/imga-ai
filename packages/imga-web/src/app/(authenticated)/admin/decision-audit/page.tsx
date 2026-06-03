"use client";

// Sprint 9.3 C — /admin/decision-audit timeline.
// Sprint 9.4 H — Suspense wrapper + Path B URL-state mirror so the
// decision_type filter survives F5 + back/forward + share-link.

import { History, Loader2 } from "lucide-react";
import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import {
  type DecisionAuditRow,
  useDecisionAuditList,
} from "@/hooks/use-decision-audit";

const DECISION_LABELS: Record<string, string> = {
  briefing_acknowledged: "Yönetici özeti onaylandı",
  briefing_dismissed: "Yönetici özeti reddedildi",
  strategic_report_approved: "Stratejik rapor onaylandı",
  strategic_report_rejected: "Stratejik rapor reddedildi",
  action_item_assigned: "Aksiyon atandı",
  action_item_priority_changed: "Aksiyon önceliği değişti",
  sla_rule_changed: "SLA kuralı değişti",
  kpi_goal_set: "KPI hedefi konuldu",
  webhook_dispatched_manually: "Webhook manuel gönderildi",
  tenant_setting_changed: "Tenant ayarı değişti",
  prompt_template_overridden: "Prompt template override edildi",
};

export default function DecisionAuditPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <DecisionAuditPageInner />
    </Suspense>
  );
}

function PageSkeleton() {
  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:p-8">
      <p className="text-muted-foreground text-sm">Yükleniyor…</p>
    </main>
  );
}

function DecisionAuditPageInner() {
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
            Karar Geçmişi
          </h1>
          <p className="text-muted-foreground text-sm">
            Yöneticilerin onay / red / atama / hedef gibi kararları
            zaman damgalı kayıt.
          </p>
        </div>
      </header>

      <div className="bg-card flex items-center gap-3 rounded-lg border p-3">
        <select
          value={decisionType}
          onChange={(e) => updateFilter(e.target.value)}
          className="border-input bg-background rounded-md border px-2 py-1 text-sm"
        >
          <option value="">Tüm karar tipleri</option>
          {Object.entries(DECISION_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <span className="text-muted-foreground ml-auto text-xs">
          {list.data?.total ?? 0} kayıt
        </span>
      </div>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      ) : list.isError ? (
        <p className="text-destructive text-sm">Liste alınamadı.</p>
      ) : !list.data || list.data.items.length === 0 ? (
        <p className="text-muted-foreground p-6 text-center text-sm">
          Kayıt yok.
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
  const [expanded, setExpanded] = useState(false);
  const label = DECISION_LABELS[row.decision_type] ?? row.decision_type;
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
              <strong>Gerekçe:</strong> {row.rationale}
            </p>
          )}
          {Object.keys(row.payload).length > 0 && (
            <pre className="bg-muted overflow-x-auto rounded p-2 font-mono">
              {JSON.stringify(row.payload, null, 2)}
            </pre>
          )}
          {row.request_id && (
            <p className="text-muted-foreground">
              req={row.request_id}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
