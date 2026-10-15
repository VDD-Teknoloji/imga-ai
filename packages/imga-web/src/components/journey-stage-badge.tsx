"use client";

// Yolculuk aşaması rozeti — /reviews liste kartı, /reviews/[id],
// /analyze sonucu ve /churn tabloları aynı rozeti kullanır.
// `stage` null → hiçbir şey çizmez (atanmamış satırda rozet gürültü);
// "ayrilma" durum rengiyle (olumsuz) vurgulanır, diğerleri nötr.

import { useTranslation } from "@/lib/i18n/use-translation";
import { isJourneyStage, journeyLabelKey } from "@/lib/journey";

export function JourneyStageBadge({
  stage,
  className,
  showUnassigned = false,
}: {
  stage: string | null | undefined;
  className?: string;
  /** true → null aşamada soluk "Aşama atanmamış" rozeti çiz (tablolar). */
  showUnassigned?: boolean;
}) {
  const { t } = useTranslation();
  if (!stage) {
    if (!showUnassigned) return null;
    return (
      <span
        className={`text-muted-foreground inline-flex items-center rounded-full border border-dashed px-2 py-0.5 text-xs ${className ?? ""}`}
      >
        {t("reviews.journey.atanmamis")}
      </span>
    );
  }
  const risky = stage === "ayrilma";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        risky
          ? "bg-sentiment-negative/10 text-sentiment-negative font-semibold"
          : "bg-primary/10 text-primary"
      } ${className ?? ""}`}
      title={t("reviews.detail.journey")}
    >
      {isJourneyStage(stage) ? t(journeyLabelKey(stage)) : stage}
    </span>
  );
}
