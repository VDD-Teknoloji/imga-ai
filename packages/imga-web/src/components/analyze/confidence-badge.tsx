"use client";

// Sprint 8.3.8 — confidence indicator for the column-mapping preview.
//
// Three bands matching the imga-api smart_parser thresholds
// (CONFIDENCE_HIGH=0.85, MEDIUM=0.55). Anything below MEDIUM lands in
// the "low" band — the UI surfaces a "lütfen kontrol edin" prompt
// because the detector is admitting it's not sure.

import { CheckCircle2, CircleDashed, AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { CONFIDENCE_HIGH, CONFIDENCE_MEDIUM } from "@/lib/types";

export type ConfidenceBand = "high" | "medium" | "low";

export function bandFor(confidence: number): ConfidenceBand {
  if (confidence >= CONFIDENCE_HIGH) return "high";
  if (confidence >= CONFIDENCE_MEDIUM) return "medium";
  return "low";
}

const BAND_CLASSES: Record<ConfidenceBand, string> = {
  high: "border-emerald-300 bg-emerald-50 text-emerald-800",
  medium: "border-amber-300 bg-amber-50 text-amber-800",
  low: "border-red-300 bg-red-50 text-red-800",
};

const BAND_LABELS: Record<ConfidenceBand, string> = {
  high: "Yüksek güven",
  medium: "Orta güven",
  low: "Düşük güven — lütfen kontrol edin",
};

export function ConfidenceBadge({
  confidence,
  className,
}: {
  confidence: number;
  className?: string;
}) {
  const band = bandFor(confidence);
  const Icon =
    band === "high"
      ? CheckCircle2
      : band === "medium"
        ? CircleDashed
        : AlertTriangle;
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1 text-xs tabular-nums",
        BAND_CLASSES[band],
        className,
      )}
      aria-label={`${BAND_LABELS[band]} (%${Math.round(confidence * 100)})`}
    >
      <Icon className="size-3" aria-hidden />
      {BAND_LABELS[band]} (%{Math.round(confidence * 100)})
    </Badge>
  );
}
