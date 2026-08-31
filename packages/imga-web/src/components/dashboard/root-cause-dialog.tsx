"use client";

// Sprint 13.1 — kök neden analizi diyaloğu (drill-down 3. seviye).
//
// Açılışta GET; kayıt varsa doğrudan render, yoksa "Analiz Oluştur"
// CTA'sı. Üretim butonu artık tenant LLM anahtarına bakılmaksızın
// etkin — platform seviyesi LLM anahtarı yedeği (IMGA_PLATFORM_LLM_KEY,
// 2026-08-26) sayesinde backend tenant anahtarı olmadan da üretiyor;
// eski proaktif kapı (kayıtlı anahtar yoksa buton hiç etkinleşmezdi)
// bu yüzden kaldırıldı. Gerçekten hiç anahtar/yedek yoksa backend yine
// de 412 döner ve bu hâlâ toast ile gösterilir.

import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type RootCauseItem,
  type RootCauseTarget,
  useGenerateRootCause,
  useRootCause,
} from "@/hooks/use-root-cause";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  open: boolean;
  onClose: () => void;
  /** null iken hiç istek atılmaz. */
  target: RootCauseTarget | null;
  primaryCategoryLabel: string;
  perspectiveLabel: string;
}

export function RootCauseDialog({
  open,
  onClose,
  target,
  primaryCategoryLabel,
  perspectiveLabel,
}: Props) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";

  const analysis = useRootCause(open ? target : null);
  const generate = useGenerateRootCause();
  const generateDisabled = generate.isPending || target === null;

  function onGenerate() {
    if (target === null) return;
    generate.mutate(target, {
      onError: (err) => {
        if (err instanceof ApiError) {
          if (err.status === 412) {
            toast.error(t("dashboard.rootCause.noCredentials"));
            return;
          }
          if (err.status === 400 || err.status === 422) {
            toast.error(err.detail);
            return;
          }
          if (err.status === 503) {
            toast.error(t("dashboard.rootCause.providerUnavailable"));
            return;
          }
        }
        toast.error(t("dashboard.rootCause.generateFailed"));
      },
    });
  }

  const result = analysis.data;

  return (
    <Dialog open={open} onOpenChange={(v) => (v ? null : onClose())}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("dashboard.rootCause.title")}</DialogTitle>
          <DialogDescription>
            {primaryCategoryLabel} › {perspectiveLabel}
          </DialogDescription>
        </DialogHeader>

        {analysis.isLoading || generate.isPending ? (
          <div className="space-y-3 py-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-24 w-full rounded-2xl" />
            <Skeleton className="h-24 w-full rounded-2xl" />
          </div>
        ) : result ? (
          <div className="space-y-4">
            <p className="text-muted-foreground text-sm leading-relaxed">
              {result.payload.summary}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("dashboard.rootCause.meta", {
                n: result.review_count.toLocaleString(numberLocale),
                model: result.model_name,
              })}
            </p>
            <ul className="space-y-3">
              {result.payload.root_causes.map((cause, i) => (
                <CauseCard key={`${cause.title}-${i}`} cause={cause} />
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm leading-relaxed">
            {t("dashboard.rootCause.empty")}
          </p>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("dashboard.rootCause.close")}
          </Button>
          <Button onClick={onGenerate} disabled={generateDisabled} className="gap-2">
            {generate.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {result ? t("dashboard.rootCause.regenerate") : t("dashboard.rootCause.generate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CauseCard({ cause }: { cause: RootCauseItem }) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  return (
    <li className="bg-muted/40 ring-foreground/5 rounded-2xl p-4 ring-1">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold">{cause.title}</h4>
        {cause.share_estimate_pct !== null && (
          <span className="text-muted-foreground text-xs tabular-nums">
            %{cause.share_estimate_pct.toLocaleString(numberLocale)}
          </span>
        )}
      </div>
      <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">{cause.description}</p>
      {cause.evidence_quotes.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {cause.evidence_quotes.map((quote, i) => (
            <li
              key={`${quote.slice(0, 24)}-${i}`}
              className="border-foreground/15 text-muted-foreground border-l-2 pl-3 text-xs italic"
            >
              {quote}
            </li>
          ))}
        </ul>
      )}
      <dl className="mt-3 grid gap-1.5 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">{t("dashboard.rootCause.affectedSurface")}</dt>
          <dd className="font-medium">{cause.affected_surface}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("dashboard.rootCause.suggestedAction")}</dt>
          <dd className="font-medium">{cause.suggested_action}</dd>
        </div>
      </dl>
    </li>
  );
}
