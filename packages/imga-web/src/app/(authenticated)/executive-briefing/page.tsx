"use client";

// Sprint 8.3.10 — /executive-briefing.
//
// Generate + view executive briefings. URL state Path B
// (?briefing_id, ?period). Disabled-CTA guard: when no active
// Gemini key the Generate button disables and a banner deep-links
// to /settings/integrations (same pattern as /strategy).

import {
  AlertTriangle,
  ArrowRight,
  ClipboardList,
  Loader2,
  Wand2,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  useBriefingTopActions,
  useExecutiveBriefing,
  useExecutiveBriefings,
  useGenerateBriefing,
} from "@/hooks/use-executive-briefings";
import { useLlmCredentials } from "@/hooks/use-llm-credentials";
import { ApiError } from "@/lib/api-client";
import {
  BRIEFING_PERIOD_LABELS,
  type BriefingKpiChange,
  type BriefingPeriod,
} from "@/lib/types";

export default function ExecutiveBriefingPage() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <Content />
    </Suspense>
  );
}

function HeaderSkeleton() {
  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-center gap-2">
        <ClipboardList className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">Yönetici Brifingi</h1>
          <p className="text-muted-foreground text-sm">Yükleniyor…</p>
        </div>
      </header>
    </main>
  );
}

function Content() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [period, setPeriodState] = useState<BriefingPeriod>(
    () => (searchParams.get("period") as BriefingPeriod) || "month",
  );
  const [briefingId, setBriefingIdState] = useState<string>(
    () => searchParams.get("briefing_id") ?? "",
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlPeriod =
      (searchParams.get("period") as BriefingPeriod) || "month";
    setPeriodState((prev) => (prev === urlPeriod ? prev : urlPeriod));
    const urlId = searchParams.get("briefing_id") ?? "";
    setBriefingIdState((prev) => (prev === urlId ? prev : urlId));
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParam(updates: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v === null || v === "") params.delete(k);
      else params.set(k, v);
    }
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const credentials = useLlmCredentials();
  const hasActiveKey = (credentials.data ?? []).some((c) => c.is_active);
  const credentialsLoaded = !credentials.isLoading;

  const list = useExecutiveBriefings(50);
  const generate = useGenerateBriefing();
  const detail = useExecutiveBriefing(briefingId || null);

  // Sprint 9.6 redesign — auto-select the latest briefing on first
  // paint when the URL doesn't already pin one. C-level operator's
  // first question is "what's the latest brief say?" — not "let me
  // generate a new one". Generation moves below the viewer.
  useEffect(() => {
    if (briefingId) return;
    const latest = list.data?.[0];
    if (!latest) return;
    setBriefingIdState(latest.id);
  }, [briefingId, list.data]);

  function onGenerate() {
    generate.mutate(
      { period },
      {
        onSuccess: (b) => {
          setBriefingIdState(b.id);
          pushParam({ briefing_id: b.id, period: b.period });
          toast.success("Brifing hazır.");
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            toast.error(err.detail);
            return;
          }
          toast.error("Brifing üretilemedi.");
        },
      },
    );
  }

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-center gap-2">
        <ClipboardList className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            Yönetici Brifingi
          </h1>
          <p className="text-muted-foreground text-sm">
            Otomatik dönemsel özet — KPI değişimleri, kritik içgörüler ve
            öncelikli aksiyonlar.
          </p>
        </div>
      </header>

      {credentialsLoaded && !hasActiveKey && (
        <div className="bg-amber-50 flex items-center gap-3 rounded-lg border border-amber-300 p-4">
          <AlertTriangle className="size-5 text-amber-600" aria-hidden />
          <div className="flex-1 text-sm">
            <p className="font-medium text-amber-900">
              Brifing oluşturmak için Gemini API anahtarı gerekli.
            </p>
            <p className="text-amber-800">
              En az bir aktif anahtar tanımlanana kadar üretim devre dışı.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => router.push("/settings/integrations")}
            className="gap-2"
          >
            Anahtar ekle <ArrowRight className="size-4" aria-hidden />
          </Button>
        </div>
      )}

      {/* Sprint 9.6 redesign — viewer first. When the URL doesn't
          pin a specific briefing, the auto-select effect above puts
          the most recent one here so the C-level user lands on
          "what's the latest decision document say?" instead of an
          empty form. */}
      {briefingId && detail.data && <BriefingViewer briefing={detail.data} />}
      {briefingId && detail.isLoading && (
        <Card>
          <CardContent className="text-muted-foreground p-6 text-sm">
            Brifing yükleniyor…
          </CardContent>
        </Card>
      )}
      {!briefingId && !list.isLoading && (list.data?.length ?? 0) === 0 && (
        <Card>
          <CardContent className="space-y-2 p-6 text-sm">
            <p className="font-medium">Henüz brifing yok.</p>
            <p className="text-muted-foreground">
              Aşağıdaki form ile ilk dönemsel brifingi üretin —
              KPI değişimleri, kritik içgörüler ve öncelikli aksiyonlar
              hazırlanır.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Sprint 9.6 redesign — generation is a single compact row, not
          its own card with a title. C-level operator looks at this
          weekly; weekly-habit affordances don't need a "Yeni brifing
          oluştur" preamble. */}
      <div className="bg-card flex flex-wrap items-end gap-3 rounded-lg border p-3">
        <div>
          <Label className="text-xs">Dönem</Label>
          <select
            value={period}
            onChange={(e) => {
              const next = e.target.value as BriefingPeriod;
              setPeriodState(next);
              pushParam({ period: next === "month" ? null : next });
            }}
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          >
            {(Object.keys(BRIEFING_PERIOD_LABELS) as BriefingPeriod[]).map(
              (p) => (
                <option key={p} value={p}>
                  {BRIEFING_PERIOD_LABELS[p]}
                </option>
              ),
            )}
          </select>
        </div>
        <Button
          onClick={onGenerate}
          disabled={generate.isPending || !hasActiveKey}
          className="gap-2"
        >
          {generate.isPending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Wand2 className="size-4" aria-hidden />
          )}
          Yeni brifing üret
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Geçmiş Brifingler</CardTitle>
        </CardHeader>
        <CardContent>
          {list.isLoading ? (
            <p className="text-sm">Yükleniyor…</p>
          ) : !list.data || list.data.length === 0 ? (
            <p className="text-muted-foreground text-sm">Henüz brifing yok.</p>
          ) : (
            <ul className="divide-y">
              {list.data.map((b) => (
                <li
                  key={b.id}
                  className="flex flex-wrap items-center gap-3 py-3"
                >
                  <Badge variant="outline">
                    {BRIEFING_PERIOD_LABELS[b.period]}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {new Date(b.generated_at).toLocaleString("tr-TR")}
                  </span>
                  <p className="flex-1 text-sm">{b.headline}</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setBriefingIdState(b.id);
                      pushParam({ briefing_id: b.id });
                    }}
                  >
                    Görüntüle
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

function BriefingViewer({
  briefing,
}: {
  briefing: import("@/lib/types").ExecutiveBriefing;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Brifing Detayı</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-base font-semibold">{briefing.headline}</p>
        <p className="text-muted-foreground text-xs">
          {briefing.date_from} → {briefing.date_to} ·{" "}
          {BRIEFING_PERIOD_LABELS[briefing.period]} ·{" "}
          {briefing.model_name}
        </p>

        {briefing.kpi_changes.length > 0 && (
          <div className="space-y-1">
            <h3 className="text-sm font-semibold">KPI Değişimleri</h3>
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {briefing.kpi_changes.map((k, idx) => (
                <KpiCard key={idx} kpi={k} />
              ))}
            </ul>
          </div>
        )}

        {briefing.critical_insights.length > 0 && (
          <div className="space-y-1">
            <h3 className="text-sm font-semibold">Kritik İçgörüler</h3>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {briefing.critical_insights.map((i, idx) => (
                <li key={idx}>{i}</li>
              ))}
            </ul>
          </div>
        )}

        {briefing.top_actions.length > 0 && (
          <TopActionsSection briefingId={briefing.id} fallback={briefing.top_actions} />
        )}
      </CardContent>
    </Card>
  );
}

function TopActionsSection({
  briefingId,
  fallback,
}: {
  briefingId: string;
  fallback: import("@/lib/types").ExecutiveBriefing["top_actions"];
}) {
  // Sprint 9.0.5-B G — prefer the linked ActionItem rows
  // (clickable, status-aware) when the backend produced them; fall
  // back to the raw LLM payload for legacy briefings (pre-9.0.5-B
  // generation, no extraction log row) so the UI never goes blank.
  const linked = useBriefingTopActions(briefingId);
  const hasLinked = (linked.data?.items?.length ?? 0) > 0;
  return (
    <div className="space-y-1">
      <h3 className="text-sm font-semibold">Öncelikli Aksiyonlar</h3>
      {hasLinked ? (
        <ul className="space-y-2">
          {linked.data!.items.map((a) => (
            <li key={a.id}>
              <a
                href={`/action-items/${a.id}`}
                className="bg-muted/40 hover:bg-muted block rounded border p-3 transition-colors"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-medium">{a.title}</p>
                  <ActionStatusBadge status={a.status} priority={a.priority} />
                </div>
                <p className="text-muted-foreground mt-1 text-xs">
                  {a.rationale ?? a.description}
                </p>
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <ul className="space-y-2">
          {fallback.map((a, idx) => (
            <li key={idx} className="bg-muted/40 rounded border p-3">
              <p className="text-sm font-medium">{a.title}</p>
              <p className="text-muted-foreground mt-1 text-xs">
                {a.rationale}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ActionStatusBadge({
  status,
  priority,
}: {
  status: "open" | "in_progress" | "done" | "cancelled";
  priority: "high" | "medium" | "low";
}) {
  const statusLabel: Record<typeof status, string> = {
    open: "Açık",
    in_progress: "Devam ediyor",
    done: "Tamamlandı",
    cancelled: "İptal",
  };
  const tone =
    status === "done"
      ? "bg-emerald-100 text-emerald-900"
      : status === "in_progress"
        ? "bg-blue-100 text-blue-900"
        : status === "cancelled"
          ? "bg-zinc-100 text-zinc-700"
          : priority === "high"
            ? "bg-red-100 text-red-900"
            : "bg-amber-100 text-amber-900";
  return (
    <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${tone}`}>
      {statusLabel[status]}
    </span>
  );
}

function KpiCard({ kpi }: { kpi: BriefingKpiChange }) {
  const tone =
    kpi.direction === "up"
      ? "bg-emerald-50 border-emerald-300 text-emerald-800"
      : kpi.direction === "down"
        ? "bg-red-50 border-red-300 text-red-800"
        : "bg-zinc-50 border-zinc-300 text-zinc-700";
  const arrow =
    kpi.direction === "up" ? "↑" : kpi.direction === "down" ? "↓" : "→";
  // Sprint 8.3.11 R2 — change_pct can be null when previous was 0 or
  // missing; the server-computed payload sets ``change_label = "yeni
  // başlangıç"`` for that case. Render the label instead of an
  // arithmetic-looking percentage.
  const hasChange = kpi.change_pct !== null && kpi.change_pct !== undefined;
  return (
    <li className={`rounded-md border p-3 ${tone}`}>
      <p className="text-xs">{kpi.metric}</p>
      <p className="text-sm font-semibold tabular-nums">
        {kpi.current.toFixed(2)}{" "}
        {hasChange ? (
          <>
            {arrow} ({(kpi.change_pct ?? 0) >= 0 ? "+" : ""}
            {(kpi.change_pct ?? 0).toFixed(1)}%)
          </>
        ) : (
          <span className="text-xs italic">
            ({kpi.change_label ?? "yeni başlangıç"})
          </span>
        )}
      </p>
      <p className="text-xs">önceki: {kpi.previous.toFixed(2)}</p>
    </li>
  );
}
