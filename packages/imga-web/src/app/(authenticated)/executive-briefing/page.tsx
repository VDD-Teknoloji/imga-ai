"use client";

// Sprint 8.3.10 — /executive-briefing.
//
// Generate + view executive briefings. URL state Path B
// (?briefing_id, ?period). Disabled-CTA guard: when no active
// Gemini key the Generate button disables and a banner deep-links
// to /settings/integrations (same pattern as /strategy).
//
// 2026-09-03 redesign (product-owner instruction: "too much text" on
// SWOT/OKR/executive summary) — same URL state, hooks, mutations, and
// pushParam call shapes as before; only the presentation changed to
// the home page's icon + short-card + click-to-expand language (see
// components/dashboard/{executive-hero,root-cause-cards,
// data-source-strip,failing-processes-card}.tsx, lib/category-icons.ts).
// Big pieces now live in ./_components/*; this file stays the URL-state
// + data-fetch shell.

import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  FileText,
  Loader2,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  useExecutiveBriefing,
  useExecutiveBriefings,
  useGenerateBriefing,
} from "@/hooks/use-executive-briefings";
import { useLlmCredentials } from "@/hooks/use-llm-credentials";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import { BRIEFING_PERIOD_LABELS, type BriefingPeriod } from "@/lib/types";

import { ActionsChecklist } from "./_components/actions-checklist";
import { BriefingHero } from "./_components/briefing-hero";
import { BriefingHistory } from "./_components/briefing-history";
import { FindingsList } from "./_components/findings-list";

export default function ExecutiveBriefingPage() {
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
          {t("briefing.page.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("briefing.page.loading")}</p>
      </header>
    </main>
  );
}

function Content() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isAdmin } = useRoleFlags();

  const [period, setPeriodState] = useState<BriefingPeriod>(
    () => (searchParams.get("period") as BriefingPeriod) || "month",
  );
  const [briefingId, setBriefingIdState] = useState<string>(
    () => searchParams.get("briefing_id") ?? "",
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlPeriod = (searchParams.get("period") as BriefingPeriod) || "month";
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
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setBriefingIdState(latest.id);
  }, [briefingId, list.data]);

  function onGenerate() {
    generate.mutate(
      { period },
      {
        onSuccess: (b) => {
          setBriefingIdState(b.id);
          pushParam({ briefing_id: b.id, period: b.period });
          toast.success(t("briefing.toast.success"));
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            toast.error(err.detail);
            return;
          }
          toast.error(t("briefing.toast.errorGeneric"));
        },
      },
    );
  }

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight md:text-3xl">
          <span className="bg-muted text-muted-foreground inline-flex size-8 shrink-0 items-center justify-center rounded-lg">
            <FileText className="size-4.5" aria-hidden />
          </span>
          {t("briefing.page.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("briefing.page.subtitle")}</p>
      </header>

      {credentialsLoaded && !hasActiveKey && (
        <div className="flex items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-5 dark:border-amber-900/50 dark:bg-amber-950/30">
          <AlertTriangle className="size-5 text-amber-600" aria-hidden />
          <div className="flex-1 text-sm">
            <p className="font-medium text-amber-900">{t("briefing.banner.title")}</p>
            <p className="text-amber-800">{t("briefing.banner.desc")}</p>
          </div>
          <Button
            variant="outline"
            onClick={() => router.push("/settings/integrations")}
            className="gap-2"
          >
            {t("briefing.banner.cta")} <ArrowRight className="size-4" aria-hidden />
          </Button>
        </div>
      )}

      {/* Sprint 9.6 redesign — viewer first. When the URL doesn't
          pin a specific briefing, the auto-select effect above puts
          the most recent one here so the C-level user lands on
          "what's the latest decision document say?" instead of an
          empty form. */}
      {briefingId && detail.data && (
        <div className="space-y-6">
          <BriefingHero briefing={detail.data} />
          <FindingsList insights={detail.data.critical_insights} />
          {detail.data.top_actions.length > 0 && (
            <ActionsChecklist briefingId={detail.data.id} fallback={detail.data.top_actions} />
          )}
        </div>
      )}
      {briefingId && detail.isLoading && (
        <div className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 text-sm ring-1">
          <p className="text-muted-foreground">{t("briefing.detail.loading")}</p>
        </div>
      )}
      {!briefingId && !list.isLoading && (list.data?.length ?? 0) === 0 && (
        <div className="rise-in shadow-soft bg-card ring-foreground/5 space-y-2 rounded-3xl p-6 text-sm ring-1">
          <p className="font-medium">{t("briefing.empty.title")}</p>
          <p className="text-muted-foreground">{t("briefing.empty.desc")}</p>
        </div>
      )}

      {/* Sprint 9.6 redesign — generation is a single compact row, not
          its own card with a title. C-level operator looks at this
          weekly; weekly-habit affordances don't need a "Yeni brifing
          oluştur" preamble. */}
      <div className="bg-card ring-foreground/5 shadow-soft flex flex-wrap items-end gap-3 rounded-2xl p-4 ring-1">
        <div>
          <Label className="text-xs">{t("briefing.period.label")}</Label>
          <select
            value={period}
            onChange={(e) => {
              const next = e.target.value as BriefingPeriod;
              setPeriodState(next);
              pushParam({ period: next === "month" ? null : next });
            }}
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          >
            {(Object.keys(BRIEFING_PERIOD_LABELS) as BriefingPeriod[]).map((p) => (
              <option key={p} value={p}>
                {t(`briefing.period.${p}`) || BRIEFING_PERIOD_LABELS[p]}
              </option>
            ))}
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
            <Sparkles className="size-4" aria-hidden />
          )}
          {t("briefing.generate.button")}
        </Button>
        {isAdmin && (
          <Link
            href="/settings/scheduled-briefings"
            className="text-muted-foreground hover:text-foreground ml-auto inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
          >
            <CalendarClock className="size-4" aria-hidden />
            {t("briefing.schedule.cta")}
          </Link>
        )}
      </div>

      <BriefingHistory
        items={list.data ?? []}
        isLoading={list.isLoading}
        selectedId={briefingId}
        onSelect={(id) => {
          setBriefingIdState(id);
          pushParam({ briefing_id: id });
        }}
      />
    </main>
  );
}
