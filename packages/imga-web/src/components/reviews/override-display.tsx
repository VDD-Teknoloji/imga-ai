"use client";

// Sprint 8.3.4 — override layer trace UI primitives.
//
// Three components, all small, sharing the OVERRIDE_LAYER_LABELS_TR
// dictionary so the review list / detail / analyze / linked-review
// surfaces present overrides identically:
//
//   <OverrideChip count />            — "+N" pill, tooltip lists layers
//   <OverrideLayerCard hit />         — single-row card on a detail page
//   <OverrideStack hits />            — stack of layer cards + summary
//
// The chip's tooltip renders only the layer labels because the chip
// is on a row that may scroll out of view; the full hit metadata
// (matched_keywords, score, detail) lands in OverrideLayerCard.

import Link from "next/link";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  type OverrideHit,
  type OverrideLayer,
  OVERRIDE_LAYER_LABELS_TR,
} from "@/lib/types";

function layerLabel(layer: string): string {
  if (layer in OVERRIDE_LAYER_LABELS_TR) {
    return OVERRIDE_LAYER_LABELS_TR[layer as OverrideLayer];
  }
  return layer;
}

// "reanalysis" kayıt-izi girdisi kural katmanı değildir — chip
// sayaçlarına girmez; yalnızca detay yığınında kart olarak görünür.
export function ruleLayerHits(hits: OverrideHit[]): OverrideHit[] {
  return hits.filter((hit) => hit.layer !== "reanalysis");
}

export function OverrideChip({
  count,
  href,
  layers,
}: {
  count: number;
  href?: string;
  layers?: string[];
}) {
  if (count === 0) {
    return <span className="text-muted-foreground text-xs">—</span>;
  }
  const tooltipBody =
    layers && layers.length > 0
      ? layers.map(layerLabel).join(" · ")
      : `${count} katman tetiklendi`;
  const pill = (
    <span className="bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200 inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-medium">
      {count}
    </span>
  );
  const trigger = href ? (
    <Link href={href} className="inline-flex items-center" aria-label={tooltipBody}>
      {pill}
    </Link>
  ) : (
    <span className="inline-flex items-center" aria-label={tooltipBody}>
      {pill}
    </span>
  );
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger render={trigger} />
        <TooltipContent>{tooltipBody}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function OverrideLayerCard({ hit }: { hit: OverrideHit }) {
  const keywords = hit.matched_keywords ?? [];
  return (
    <div className="bg-card rounded-md border p-3">
      <div className="flex items-baseline justify-between gap-3">
        <h4 className="text-sm font-semibold">{layerLabel(hit.layer)}</h4>
        {typeof hit.score === "number" && (
          <span className="text-muted-foreground font-mono text-xs">
            skor {hit.score >= 0 ? "+" : ""}
            {hit.score.toFixed(2)}
          </span>
        )}
      </div>
      {keywords.length > 0 && (
        <p className="text-muted-foreground mt-1 text-xs">
          Eşleşen:{" "}
          <span className="text-foreground font-mono">
            {keywords.join(", ")}
          </span>
        </p>
      )}
      {hit.detail && (
        <p className="text-muted-foreground mt-1 text-xs italic">{hit.detail}</p>
      )}
    </div>
  );
}

export function OverrideStack({ hits }: { hits: OverrideHit[] }) {
  if (hits.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        Bu analiz için hiçbir kural katmanı tetiklenmedi.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {hits.map((hit, i) => (
        <OverrideLayerCard key={`${hit.layer}-${i}`} hit={hit} />
      ))}
    </div>
  );
}

export { layerLabel as overrideLayerLabel };
