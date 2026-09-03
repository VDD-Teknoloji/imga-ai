"use client";

// 2026-09-03 (SWOT/OKR görsel sadeleştirme) — eski SwotViewer paragraf
// ağırlıklıydı (4 renkli kutu, her biri tam metin madde listesi + ayrı
// bir öneri listesi). PO talimatı: "Everything is too much text" —
// kartlar kısa ve dikkat çekici olsun, detay tıklama arkasında dursun,
// canlılık ikon + küçük görsellerden gelsin. Her çeyrek artık ikonlu
// yumuşak-tonlu bir başlık + tek satırlık (line-clamp) madde listesi;
// tam açıklama + kanıt "Detayları gör" arkasında (root-cause-cards.tsx
// ile aynı ChevronRight/ChevronDown + showDetails/hideDetails deseni —
// wording aynı olduğu için ayrı bir anahtar açılmadı, doğrudan
// dashboard.rootCauseCards.* çevirileri kullanıldı).

import {
  ChevronDown,
  ChevronRight,
  Lightbulb,
  ListChecks,
  Loader2,
  Quote,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useExtractFromReport } from "@/hooks/use-action-items";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { StrategicReportDetail, SwotItem, SwotPayload, SwotRecommendation } from "@/lib/types";

import { DownloadPdfButton } from "./download-pdf-button";
import { ReportMetaStrip } from "./report-meta-strip";

interface QuadrantConfig {
  key: keyof Pick<SwotPayload, "strengths" | "weaknesses" | "opportunities" | "threats">;
  labelKey: string;
  icon: LucideIcon;
  badgeBg: string;
  badgeFg: string;
  headerBg: string;
}

// Renk eşlemesi görev talimatına birebir: strengths=emerald/ShieldCheck,
// weaknesses=amber/TriangleAlert, opportunities=sky/Lightbulb,
// threats=red/ShieldAlert. strengths/threats için mevcut sentiment
// token'ları (text-sentiment-positive/negative) kullanılır — semantik
// olarak tam örtüşüyorlar; weaknesses/opportunities için karşılığı
// olmayan amber/sky Tailwind paleti.
const SWOT_QUADRANTS: readonly QuadrantConfig[] = [
  {
    key: "strengths",
    labelKey: "dashboard.strategy.swot.strengths",
    icon: ShieldCheck,
    badgeBg: "bg-sentiment-positive/15",
    badgeFg: "text-sentiment-positive",
    headerBg: "bg-sentiment-positive/10",
  },
  {
    key: "weaknesses",
    labelKey: "dashboard.strategy.swot.weaknesses",
    icon: TriangleAlert,
    badgeBg: "bg-amber-500/15",
    badgeFg: "text-amber-700 dark:text-amber-400",
    headerBg: "bg-amber-500/10",
  },
  {
    key: "opportunities",
    labelKey: "dashboard.strategy.swot.opportunities",
    icon: Lightbulb,
    badgeBg: "bg-sky-500/15",
    badgeFg: "text-sky-700 dark:text-sky-400",
    headerBg: "bg-sky-500/10",
  },
  {
    key: "threats",
    labelKey: "dashboard.strategy.swot.threats",
    icon: ShieldAlert,
    badgeBg: "bg-sentiment-negative/15",
    badgeFg: "text-sentiment-negative",
    headerBg: "bg-sentiment-negative/10",
  },
];

export function SwotViewer({ report }: { report: StrategicReportDetail }) {
  const { t } = useTranslation();
  const payload = report.output_payload as unknown as SwotPayload;
  const recommendations = payload.strategic_recommendations ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle className="text-base">{t("dashboard.strategy.swot.reportTitle")}</CardTitle>
          <div className="mt-1.5">
            <ReportMetaStrip report={report} />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ExtractActionItemsButton reportId={report.id} />
          <DownloadPdfButton reportId={report.id} reportType="swot" />
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {SWOT_QUADRANTS.map((config) => (
            <SwotQuadrant key={config.key} config={config} items={payload[config.key] ?? []} />
          ))}
        </div>

        {recommendations.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">
              {t("dashboard.strategy.swot.recommendations")}
            </h3>
            <ul className="space-y-2">
              {recommendations.map((rec, idx) => (
                <RecommendationRow key={idx} rec={rec} />
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SwotQuadrant({ config, items }: { config: QuadrantConfig; items: SwotItem[] }) {
  const { t } = useTranslation();
  const Icon = config.icon;
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  function toggle(idx: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  return (
    <div className="rise-in ring-foreground/10 overflow-hidden rounded-2xl ring-1">
      <div className={`flex items-center gap-2.5 px-4 py-3 ${config.headerBg}`}>
        <span
          className={`inline-flex size-7 shrink-0 items-center justify-center rounded-full ${config.badgeBg} ${config.badgeFg}`}
          aria-hidden
        >
          <Icon className="size-4" />
        </span>
        <h3 className="text-sm font-semibold">{t(config.labelKey)}</h3>
      </div>
      <div className="bg-card p-4">
        {items.length === 0 ? (
          <p className="text-muted-foreground text-xs">{t("dashboard.strategy.swot.noItems")}</p>
        ) : (
          <ul className="space-y-2.5">
            {items.map((item, idx) => {
              const isOpen = expanded.has(idx);
              return (
                <li key={idx}>
                  <button
                    type="button"
                    onClick={() => toggle(idx)}
                    aria-expanded={isOpen}
                    className="flex w-full items-start justify-between gap-2 text-left"
                  >
                    <span className="line-clamp-1 text-sm font-medium">{item.title}</span>
                    <span className="mt-0.5 flex shrink-0 items-center gap-1">
                      {item.evidence && (
                        <span
                          className="border-foreground/15 text-muted-foreground inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[10px]"
                          aria-label={t("dashboard.strategy.swot.hasEvidence")}
                        >
                          <Quote className="size-2.5" aria-hidden />1
                        </span>
                      )}
                      {isOpen ? (
                        <ChevronDown className="text-muted-foreground size-3.5" aria-hidden />
                      ) : (
                        <ChevronRight className="text-muted-foreground size-3.5" aria-hidden />
                      )}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="mt-1.5 space-y-1.5 pr-5">
                      <p className="text-muted-foreground text-xs leading-relaxed">
                        {item.description}
                      </p>
                      {item.evidence && (
                        <p className="text-muted-foreground text-xs leading-relaxed italic">
                          {t("dashboard.strategy.swot.evidence", { text: item.evidence })}
                        </p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

const SWOT_PRIORITY_TONE: Record<string, string> = {
  yüksek: "bg-red-50 border-red-300 text-red-800",
  orta: "bg-amber-50 border-amber-300 text-amber-800",
  düşük: "bg-emerald-50 border-emerald-300 text-emerald-800",
};

const SWOT_TONE_FALLBACK = "bg-gray-50 border-gray-300 text-gray-800";

// Kısa değilse (LLM description'ı birkaç cümle geldiyse) satır
// kırpılır, "Detayları gör" arkasında tamamı açılır — kısaysa gereksiz
// bir tıklama katmanı eklenmez (PO: "silence when there is nothing to
// say" ile aynı ilke).
const RECOMMENDATION_CLAMP_THRESHOLD = 140;

function RecommendationRow({ rec }: { rec: SwotRecommendation }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const priorityTone = rec.priority
    ? (SWOT_PRIORITY_TONE[rec.priority.toLowerCase()] ?? SWOT_TONE_FALLBACK)
    : SWOT_TONE_FALLBACK;
  const impactTone = rec.estimated_impact
    ? (SWOT_PRIORITY_TONE[rec.estimated_impact.toLowerCase()] ?? SWOT_TONE_FALLBACK)
    : SWOT_TONE_FALLBACK;
  // description ham JSONB'den geliyor (strict:false persist) — eski bir
  // raporda hiç gelmemiş olabilir; `?? ""` .length'in undefined üzerinde
  // patlamasını engeller (proje notu: "LLM-payload şekil sertleştirmesi").
  const description = rec.description ?? "";
  const needsClamp = description.length > RECOMMENDATION_CLAMP_THRESHOLD;

  return (
    <li className="bg-card space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium">{rec.title}</p>
        {rec.priority && (
          <Badge variant="outline" className={`text-xs ${priorityTone}`}>
            {t("dashboard.strategy.swot.priorityBadge", { value: rec.priority })}
          </Badge>
        )}
        {rec.estimated_impact && (
          <Badge variant="outline" className={`text-xs ${impactTone}`}>
            {t("dashboard.strategy.swot.impactBadge", { value: rec.estimated_impact })}
          </Badge>
        )}
      </div>
      <p className={`text-muted-foreground text-sm ${!open && needsClamp ? "line-clamp-2" : ""}`}>
        {description}
      </p>
      {needsClamp && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs font-medium transition-colors"
        >
          {open ? (
            <ChevronDown className="size-3.5" aria-hidden />
          ) : (
            <ChevronRight className="size-3.5" aria-hidden />
          )}
          {open
            ? t("dashboard.rootCauseCards.hideDetails")
            : t("dashboard.rootCauseCards.showDetails")}
        </button>
      )}
    </li>
  );
}

// Sprint 8.3.10 — SWOT stratejik önerilerini takip edilebilir aksiyon
// maddelerine çıkarır. Yalnız SWOT görüntüleyicide kullanılıyor —
// OKR'nin kendi çıkarma akışı yok.
function ExtractActionItemsButton({ reportId }: { reportId: string }) {
  const { t } = useTranslation();
  const router = useRouter();
  const extract = useExtractFromReport();
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={extract.isPending}
      onClick={() =>
        extract.mutate(reportId, {
          onSuccess: (rows) => {
            toast.success(t("dashboard.strategy.extract.added", { n: rows.length }), {
              action: {
                label: t("dashboard.common.view"),
                onClick: () => router.push("/action-items"),
              },
            });
          },
          onError: () => toast.error(t("dashboard.strategy.extract.failed")),
        })
      }
      className="gap-1"
    >
      {extract.isPending ? (
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
      ) : (
        <ListChecks className="size-3.5" aria-hidden />
      )}
      {t("dashboard.strategy.extract.button")}
    </Button>
  );
}
