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

import { OverrideStack, overrideLayerLabel } from "@/components/reviews/override-display";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAnalyze } from "@/hooks/use-analyze";
import { useManualPromoteReview } from "@/hooks/use-reviews";
import { ApiError } from "@/lib/api-client";
import type { ReviewDecision, TenantAnalyzeResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const PROMOTABLE_DECISIONS: ReadonlySet<ReviewDecision> = new Set([
  "skipped_mode",
  "skipped_threshold",
  "skipped_belirsiz",
]);

const TEXT_MAX_LENGTH = 10_000;

/**
 * Manual analyze page. Calls `POST /tenants/me/analyze` (Sprint
 * 7.5.5 / Alt-Faz 3) and renders the resulting decision branch.
 *
 * Source field is intentionally absent in this iteration — see
 * roadmap C7 for the deferred design alongside webhook ingestion.
 */
export default function AnalyzePage() {
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
        toast.error("NPS 0 ile 10 arasında olmalı.");
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
              toast.error("Metin 10.000 karakteri aşıyor.");
              return;
            }
            if (err.status === 403) {
              toast.error("Bu işlem için yetkin yok.");
              return;
            }
          }
          toast.error("Analiz tamamlanamadı.");
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
          Yorum Analiz Et
        </h1>
        <p className="text-muted-foreground text-sm">
          Müşteri yorumunu yapıştırın. Duygu ve kategori analizi yapılır; kurum
          otomasyon ayarına göre gerekirse Ticket otomatik açılır.
        </p>
      </header>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="space-y-2">
          <Label htmlFor="analyze-text">Yorum metni</Label>
          <Textarea
            id="analyze-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Örnek: Kargom 5 gündür gelmedi, takip numarası da çalışmıyor."
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
            {charCount.toLocaleString("tr-TR")} / {TEXT_MAX_LENGTH.toLocaleString("tr-TR")} karakter
          </p>
        </div>
        <div className="max-w-[200px] space-y-1">
          <Label htmlFor="analyze-nps" className="text-xs">
            NPS (opsiyonel, 0–10)
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
                Analiz ediliyor...
              </>
            ) : (
              <>
                Analiz Et
                <ArrowRight className="size-4" aria-hidden />
              </>
            )}
          </Button>
          {result || analyze.isError ? (
            <Button type="button" variant="ghost" onClick={reset} disabled={analyze.isPending}>
              Yeni analiz
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
  const [expanded, setExpanded] = useState(false);
  if (hits.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Tetiklenen Katmanlar</CardTitle>
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
          {expanded ? "Detayları Gizle" : "Detayları Göster"}
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
  const a = result.analysis;
  const sentimentVariant =
    a.sentiment_label === "NEGATIF"
      ? "destructive"
      : a.sentiment_label === "POZITIF"
        ? "default"
        : "secondary";
  const categoryCode = a.categorization?.primary ?? "belirsiz";
  const confidencePct =
    a.categorization != null ? Math.round(a.categorization.primary_confidence * 100) : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Analiz sonucu</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Metric label="Duygu">
          <div className="flex items-center gap-2">
            <Badge variant={sentimentVariant} className="px-2 py-0.5">
              {a.sentiment_label}
            </Badge>
            <span className="text-muted-foreground text-xs tabular-nums">
              {a.sentiment_score.toFixed(2)}
            </span>
          </div>
        </Metric>
        <Metric label="Kategori">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="px-2 py-0.5">
              {categoryCode}
            </Badge>
            {confidencePct != null ? (
              <span className="text-muted-foreground text-xs tabular-nums">
                %{confidencePct} güven
              </span>
            ) : null}
          </div>
        </Metric>
        <Metric label="Şirket perspektifi">
          {result.company_perspective_code === null ? (
            <span className="text-muted-foreground text-sm italic">eşleşme yok</span>
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
          <Metric label="Özet" className="sm:col-span-2">
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
  title: string;
  message: string;
}

const DECISION_VARIANTS: Record<ReviewDecision, DecisionVariant> = {
  create: {
    variant: "success",
    Icon: CheckCircle2,
    title: "Otomatik Ticket açıldı",
    message: "Kurumunuzun otomasyon ayarı bu yoruma göre yeni bir Ticket açtı.",
  },
  skipped_dedup: {
    variant: "info",
    Icon: Info,
    title: "Aynı metin son 24 saatte zaten analiz edildi",
    message: "Tekrar Ticket açılmadı; mevcut Ticket'ın altında çalışmaya devam et.",
  },
  skipped_mode: {
    variant: "info",
    Icon: ShieldOff,
    title: "Otomasyon modu manuel — Ticket açılmadı",
    message:
      "Manuel modda yalnızca duygu ve kategori analizi yapılır; Ticket açma için kurum ayarlarını Tam veya Yarı otomatik yap.",
  },
  skipped_threshold: {
    variant: "info",
    Icon: CircleAlert,
    title: "Eşik altı — Ticket açılmadı",
    message:
      "Kurum otomasyon eşiği bu yorumu otomatik Ticket açmak için yeterli bulmadı; metni manuel inceleyebilirsin.",
  },
  skipped_belirsiz: {
    variant: "info",
    Icon: HelpCircle,
    title: "Kategori belirsiz — manuel sınıflandırma gerekli",
    message:
      "Sınıflandırıcı bu metni emin bir kategoriye yerleştiremedi. Hangi modda olursan ol, belirsiz yorumlardan otomatik Ticket açılmaz.",
  },
};

function DecisionCard({
  result,
  onPromoted,
}: {
  result: TenantAnalyzeResponse;
  onPromoted: (ticketId: string) => void;
}) {
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
        toast.success("Manuel olarak Ticket açıldı.");
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error("Bu işlem için yetkin yok.");
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          toast.error("Bu analiz zaten bir Ticket'a bağlı.");
          return;
        }
        toast.error("Ticket açılamadı.");
      },
    });
  }

  return (
    <Card className={cardBorder}>
      <CardHeader className="flex flex-row items-start gap-3">
        <Icon className={cn("mt-0.5 size-5 shrink-0", iconClass)} aria-hidden />
        <div className="space-y-1">
          <CardTitle className="text-base">{variant.title}</CardTitle>
          <p className="text-muted-foreground text-sm">{variant.message}</p>
        </div>
      </CardHeader>
      {result.ticket_id ? (
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button render={<Link href={`/tickets/${result.ticket_id}`} />} className="gap-2">
            {result.decision === "create" ? "Yeni Ticket'a git" : "Mevcut Ticket'a git"}
            <ArrowRight className="size-4" aria-hidden />
          </Button>
          <span className="text-muted-foreground text-xs">
            Ticket ID: <code className="font-mono">{result.ticket_id.slice(0, 8)}</code>
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
            Yine de Ticket Aç
          </Button>
          <span className="text-muted-foreground text-xs">
            Sistem güvenini geçersiz kıl — manuel olarak Ticket aç.
          </span>
        </CardContent>
      ) : null}
    </Card>
  );
}
