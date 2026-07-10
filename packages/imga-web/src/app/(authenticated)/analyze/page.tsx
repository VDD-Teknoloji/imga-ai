"use client";

import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  HelpCircle,
  Info,
  Loader2,
  ShieldOff,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { OverrideStack, overrideLayerLabel } from "@/components/reviews/override-display";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAnalyze } from "@/hooks/use-analyze";
import { useCategories } from "@/hooks/use-categories";
import { useManualPromoteReview } from "@/hooks/use-reviews";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { ReviewDecision, TenantAnalyzeResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const PROMOTABLE_DECISIONS: ReadonlySet<ReviewDecision> = new Set([
  "skipped_mode",
  "skipped_threshold",
  "skipped_belirsiz",
]);

const TEXT_MAX_LENGTH = 10_000;

// reviews/page.tsx ile aynı harita — ham POZITIF/NEGATIF/NÖTR enum'u
// yerine locale'e uygun etiket (HATA: i18n A-listesi).
const SENTIMENT_LABEL_KEYS: Record<string, string> = {
  NEGATIF: "reviews.sentiment.negatif",
  POZITIF: "reviews.sentiment.pozitif",
  "NÖTR": "reviews.sentiment.notr",
};

export default function AnalyzePage() {
  return (
    <RequireRole level="write">
      <AnalyzePageInner />
    </RequireRole>
  );
}

/**
 * Manual analyze page. Calls `POST /tenants/me/analyze` (Sprint
 * 7.5.5 / Alt-Faz 3) and renders the resulting decision branch.
 *
 * Source field is intentionally absent in this iteration — see
 * roadmap C7 for the deferred design alongside webhook ingestion.
 */
function AnalyzePageInner() {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  // Sprint 8.3.5 — optional NPS, kept as string in state so an empty
  // input round-trips without coercing to 0. Validated to 0..10 below;
  // the backend re-validates on its side.
  const [npsInput, setNpsInput] = useState<string>("");
  const [result, setResult] = useState<TenantAnalyzeResponse | null>(null);
  const analyze = useAnalyze();

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (trimmed.length === 0) return;
    setResult(null);
    let npsScore: number | undefined;
    if (npsInput.trim().length > 0) {
      const parsed = Number.parseInt(npsInput.trim(), 10);
      if (Number.isFinite(parsed) && parsed >= 0 && parsed <= 10) {
        npsScore = parsed;
      } else {
        toast.error(t("analyze.manual.npsRange"));
        return;
      }
    }
    analyze.mutate(
      { text: trimmed, nps_score: npsScore },
      {
        onSuccess: (data) => {
          setResult(data);
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.status === 422) {
              toast.error(t("analyze.manual.textTooLong"));
              return;
            }
            if (err.status === 403) {
              toast.error(t("analyze.manual.noPermission"));
              return;
            }
          }
          toast.error(t("analyze.manual.analyzeFailed"));
        },
      },
    );
  }

  function reset() {
    setText("");
    setNpsInput("");
    setResult(null);
  }

  const charCount = text.length;
  const overLimit = charCount > TEXT_MAX_LENGTH;
  const submitDisabled = text.trim().length === 0 || overLimit || analyze.isPending;

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("analyze.manual.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("analyze.manual.subtitle")}
        </p>
      </header>

      {/* noValidate — HATA-07: tarayıcının kendi dilindeki min/max
          balonu yerine handleSubmit'teki TR toast çalışsın. */}
      <form onSubmit={handleSubmit} noValidate className="space-y-3">
        <div className="space-y-2">
          <Label htmlFor="analyze-text">{t("analyze.manual.textLabel")}</Label>
          <Textarea
            id="analyze-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("analyze.manual.textPlaceholder")}
            rows={6}
            maxLength={TEXT_MAX_LENGTH}
            disabled={analyze.isPending}
            aria-invalid={overLimit || undefined}
            aria-describedby="analyze-charcount"
          />
          <p
            id="analyze-charcount"
            className={cn(
              "text-muted-foreground text-xs tabular-nums",
              overLimit && "text-destructive",
            )}
          >
            {t("analyze.manual.charCount", {
              count: charCount.toLocaleString("tr-TR"),
              max: TEXT_MAX_LENGTH.toLocaleString("tr-TR"),
            })}
          </p>
        </div>
        <div className="max-w-[200px] space-y-1">
          <Label htmlFor="analyze-nps" className="text-xs">
            {t("analyze.manual.npsLabel")}
          </Label>
          <input
            id="analyze-nps"
            type="number"
            min={0}
            max={10}
            step={1}
            value={npsInput}
            onChange={(e) => setNpsInput(e.target.value)}
            disabled={analyze.isPending}
            placeholder="—"
            className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm tabular-nums"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={submitDisabled} className="gap-2">
            {analyze.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden />
                {t("analyze.manual.analyzing")}
              </>
            ) : (
              <>
                {t("analyze.manual.submit")}
                <ArrowRight className="size-4" aria-hidden />
              </>
            )}
          </Button>
          {result || analyze.isError ? (
            <Button type="button" variant="ghost" onClick={reset} disabled={analyze.isPending}>
              {t("analyze.manual.newAnalysis")}
            </Button>
          ) : null}
        </div>
      </form>

      {result ? (
        <AnalysisOutput
          result={result}
          onPromoted={(ticketId) =>
            setResult((prev) => (prev ? { ...prev, ticket_id: ticketId } : prev))
          }
        />
      ) : null}
    </main>
  );
}

// --- result rendering ---------------------------------------------------

function AnalysisOutput({
  result,
  onPromoted,
}: {
  result: TenantAnalyzeResponse;
  onPromoted: (ticketId: string) => void;
}) {
  return (
    <div className="space-y-4">
      <AnalysisSummary result={result} />
      <OverrideHits hits={result.analysis.overrides_applied} />
      <DecisionCard result={result} onPromoted={onPromoted} />
    </div>
  );
}

// Pills + expandable detail. Hidden when nothing fired so the page
// stays compact in the common neutral-text case.
function OverrideHits({ hits }: { hits: TenantAnalyzeResponse["analysis"]["overrides_applied"] }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  if (hits.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("analyze.manual.triggeredLayers")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {hits.map((hit, i) => (
            <Badge key={`${hit.layer}-${i}`} variant="secondary">
              {overrideLayerLabel(hit.layer)}
            </Badge>
          ))}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setExpanded((v) => !v)}
          className="gap-1"
        >
          {expanded ? t("analyze.manual.hideDetails") : t("analyze.manual.showDetails")}
          {expanded ? (
            <ChevronUp className="size-4" aria-hidden />
          ) : (
            <ChevronDown className="size-4" aria-hidden />
          )}
        </Button>
        {expanded && <OverrideStack hits={hits} />}
      </CardContent>
    </Card>
  );
}

function AnalysisSummary({ result }: { result: TenantAnalyzeResponse }) {
  const { t } = useTranslation();
  const categories = useCategories();
  const a = result.analysis;
  const sentimentVariant =
    a.sentiment_label === "NEGATIF"
      ? "destructive"
      : a.sentiment_label === "POZITIF"
        ? "default"
        : "secondary";
  const sentimentKey = SENTIMENT_LABEL_KEYS[a.sentiment_label];
  const categoryCode = a.categorization?.primary ?? "belirsiz";
  const categoryLabel =
    categories.data?.find((c) => c.code === categoryCode)?.label_tr ??
    categoryCode;
  const confidencePct =
    a.categorization != null ? Math.round(a.categorization.primary_confidence * 100) : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("analyze.manual.resultTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Metric label={t("analyze.manual.sentiment")}>
          <div className="flex items-center gap-2">
            <Badge variant={sentimentVariant} className="px-2 py-0.5">
              {sentimentKey ? t(sentimentKey) : a.sentiment_label}
            </Badge>
            <span className="text-muted-foreground text-xs tabular-nums">
              {a.sentiment_score.toFixed(2)}
            </span>
          </div>
        </Metric>
        <Metric label={t("analyze.manual.category")}>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="px-2 py-0.5">
              {categoryLabel}
            </Badge>
            {confidencePct != null ? (
              <span className="text-muted-foreground text-xs tabular-nums">
                {t("analyze.manual.confidenceSuffix", { pct: confidencePct })}
              </span>
            ) : null}
          </div>
        </Metric>
        <Metric label={t("analyze.manual.companyPerspective")}>
          {result.company_perspective_code === null ? (
            <span className="text-muted-foreground text-sm italic">{t("analyze.manual.noMatch")}</span>
          ) : (
            <Badge variant="outline" className="px-2 py-0.5">
              {result.company_perspective_label_tr ?? result.company_perspective_code}
            </Badge>
          )}
        </Metric>
        {a.sla_detected ? (
          <Metric label="SLA">
            <span className="text-sm">{a.sla_detected}</span>
          </Metric>
        ) : null}
        {a.summary ? (
          <Metric label={t("analyze.manual.summary")} className="sm:col-span-2">
            <p className="text-foreground text-sm">{a.summary}</p>
          </Metric>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <span className="text-muted-foreground text-xs font-medium">{label}</span>
      {children}
    </div>
  );
}

// --- decision branch card ----------------------------------------------

interface DecisionVariant {
  variant: "success" | "info" | "warning";
  Icon: typeof Sparkles;
  titleKey: string;
  messageKey: string;
}

const DECISION_VARIANTS: Record<ReviewDecision, DecisionVariant> = {
  create: {
    variant: "success",
    Icon: CheckCircle2,
    titleKey: "analyze.manual.decision.create.title",
    messageKey: "analyze.manual.decision.create.message",
  },
  skipped_dedup: {
    variant: "info",
    Icon: Info,
    titleKey: "analyze.manual.decision.dedup.title",
    messageKey: "analyze.manual.decision.dedup.message",
  },
  skipped_mode: {
    variant: "info",
    Icon: ShieldOff,
    titleKey: "analyze.manual.decision.mode.title",
    messageKey: "analyze.manual.decision.mode.message",
  },
  skipped_threshold: {
    variant: "info",
    Icon: CircleAlert,
    titleKey: "analyze.manual.decision.threshold.title",
    messageKey: "analyze.manual.decision.threshold.message",
  },
  skipped_belirsiz: {
    variant: "info",
    Icon: HelpCircle,
    titleKey: "analyze.manual.decision.belirsiz.title",
    messageKey: "analyze.manual.decision.belirsiz.message",
  },
};

function DecisionCard({
  result,
  onPromoted,
}: {
  result: TenantAnalyzeResponse;
  onPromoted: (ticketId: string) => void;
}) {
  const { t } = useTranslation();
  const variant = DECISION_VARIANTS[result.decision];
  const Icon = variant.Icon;
  const cardBorder =
    variant.variant === "success"
      ? "border-emerald-500/40"
      : variant.variant === "warning"
        ? "border-amber-500/40"
        : "border-primary/30";
  const iconClass =
    variant.variant === "success"
      ? "text-emerald-600"
      : variant.variant === "warning"
        ? "text-amber-600"
        : "text-primary";

  const promote = useManualPromoteReview();
  const canPromote = result.ticket_id == null && PROMOTABLE_DECISIONS.has(result.decision);

  function handlePromote() {
    promote.mutate(result.review_id, {
      onSuccess: (data) => {
        onPromoted(data.ticket_id);
        toast.success(t("analyze.manual.promoteSuccess"));
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error(t("analyze.manual.noPermission"));
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          // 409'un iki kaynağı var: zaten bağlı VE yapılandırılmamış
          // kategori — API detail'ine göre ayrıştır (UAT HATA-03 FE).
          toast.error(
            err.detail.includes("not configured")
              ? t("analyze.manual.categoryNotConfigured")
              : t("analyze.manual.alreadyLinked"),
          );
          return;
        }
        toast.error(t("analyze.manual.promoteFailed"));
      },
    });
  }

  return (
    <Card className={cardBorder}>
      <CardHeader className="flex flex-row items-start gap-3">
        <Icon className={cn("mt-0.5 size-5 shrink-0", iconClass)} aria-hidden />
        <div className="space-y-1">
          <CardTitle className="text-base">{t(variant.titleKey)}</CardTitle>
          <p className="text-muted-foreground text-sm">{t(variant.messageKey)}</p>
        </div>
      </CardHeader>
      {result.ticket_id ? (
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button render={<Link href={`/tickets/${result.ticket_id}`} />} className="gap-2">
            {result.decision === "create"
              ? t("analyze.manual.goNewTicket")
              : t("analyze.manual.goExistingTicket")}
            <ArrowRight className="size-4" aria-hidden />
          </Button>
          <span className="text-muted-foreground text-xs">
            {t("analyze.manual.ticketIdLabel")}{" "}
            <code className="font-mono">{result.ticket_id.slice(0, 8)}</code>
          </span>
        </CardContent>
      ) : canPromote ? (
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={handlePromote}
            disabled={promote.isPending}
            className="gap-2"
          >
            {promote.isPending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <ArrowRight className="size-4" aria-hidden />
            )}
            {t("analyze.manual.promoteAnyway")}
          </Button>
          <span className="text-muted-foreground text-xs">
            {t("analyze.manual.promoteHint")}
          </span>
        </CardContent>
      ) : null}
    </Card>
  );
}
