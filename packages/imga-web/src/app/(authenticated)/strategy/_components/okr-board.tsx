"use client";

// 2026-09-03 (SWOT/OKR görsel sadeleştirme) — eski OkrViewer her hedefi
// tek bir uzun kart olarak basıyordu: başlık + gerekçe italik paragraf +
// üç sütunlu (Metrik/Mevcut/Hedef) tanım listesi. PO talimatı: kartlar
// kısa, detay tıklama arkasında, canlılık küçük görsellerden gelsin.
// Her hedef artık ikonlu bir kart; anahtar sonuçlar kısa satır + (sayısal
// değer varsa) ince bir SVG-siz CSS çubuğu, yoksa nötr bir durum
// rozeti; gerekçe "Detayları gör" arkasında (root-cause-cards.tsx ile
// aynı toggle deseni, aynı wording — ayrı anahtar açılmadı).

import { ChevronDown, ChevronRight, Target } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMounted } from "@/hooks/use-count-up";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { OkrKeyResult, OkrObjective, OkrPayload, StrategicReportDetail } from "@/lib/types";

import { DownloadPdfButton } from "./download-pdf-button";
import { ReportMetaStrip } from "./report-meta-strip";

export function OkrViewer({
  report,
  sourceReport,
}: {
  report: StrategicReportDetail;
  sourceReport: StrategicReportDetail | null;
}) {
  const { t } = useTranslation();
  const payload = report.output_payload as unknown as OkrPayload;
  const objectives = payload.objectives ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle className="text-base">{t("dashboard.strategy.okr.reportTitle")}</CardTitle>
          <div className="mt-1.5">
            <ReportMetaStrip report={report} sourceReport={sourceReport} />
          </div>
        </div>
        <DownloadPdfButton reportId={report.id} reportType="okr" />
      </CardHeader>
      <CardContent>
        {objectives.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t("dashboard.strategy.okr.noObjectives")}
          </p>
        ) : (
          <ul className="space-y-4">
            {objectives.map((obj, idx) => (
              <ObjectiveCard key={idx} obj={obj} index={idx} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ObjectiveCard({ obj, index }: { obj: OkrObjective; index: number }) {
  const { t } = useTranslation();
  const [showRationale, setShowRationale] = useState(false);
  const keyResults = obj.key_results ?? [];

  return (
    <li
      className="rise-in shadow-soft bg-card ring-foreground/5 rounded-2xl p-4 ring-1 md:p-5"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="flex items-start gap-2.5">
        <span
          className="bg-primary/10 text-primary inline-flex size-8 shrink-0 items-center justify-center rounded-full"
          aria-hidden
        >
          <Target className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground text-[11px] font-semibold tracking-wide uppercase">
            {t("dashboard.strategy.okr.objective", { n: index + 1 })}
          </p>
          <p className="mt-0.5 text-sm font-semibold text-balance">{obj.objective}</p>
        </div>
      </div>

      {keyResults.length > 0 && (
        <div className="mt-4">
          <p className="text-muted-foreground text-[11px] font-semibold tracking-wide uppercase">
            {t("dashboard.strategy.okr.keyResults")}
          </p>
          <ul className="mt-2 space-y-2">
            {keyResults.map((kr, krIdx) => (
              <KeyResultRow key={krIdx} kr={kr} />
            ))}
          </ul>
        </div>
      )}

      {obj.rationale && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowRationale((v) => !v)}
            aria-expanded={showRationale}
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs font-medium transition-colors"
          >
            {showRationale ? (
              <ChevronDown className="size-3.5" aria-hidden />
            ) : (
              <ChevronRight className="size-3.5" aria-hidden />
            )}
            {showRationale
              ? t("dashboard.rootCauseCards.hideDetails")
              : t("dashboard.rootCauseCards.showDetails")}
          </button>
          {showRationale && (
            <p className="text-muted-foreground border-foreground/10 mt-2 border-t pt-2 text-xs leading-relaxed italic">
              {t("dashboard.strategy.okr.rationale", { text: obj.rationale })}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/** "42", "%42", "4,2/5", "120 gün" gibi metriklerin baş kısmındaki
 *  sayıyı çıkarır — backend baseline/target'ı serbest metin olarak
 *  üretir (response_schema string), kesin sayısal tip garantisi yok.
 *  null/undefined kabul eder: output_payload strict:false ham JSONB
 *  olarak persist edilir (bkz. proje notu "LLM-payload şekil
 *  sertleştirmesi") — eski bir raporda alan hiç gelmemiş olabilir. */
function parseNumeric(value: string | null | undefined): number | null {
  if (!value) return null;
  const match = value.replace(",", ".").match(/-?\d+(\.\d+)?/);
  if (!match) return null;
  const n = Number(match[0]);
  return Number.isFinite(n) ? n : null;
}

function KeyResultRow({ kr }: { kr: OkrKeyResult }) {
  const { t } = useTranslation();
  const baselineNum = parseNumeric(kr.baseline);
  const targetNum = parseNumeric(kr.target);
  const hasNumbers = baselineNum !== null && targetNum !== null;
  // Sayısal olmayan (nitel) anahtar sonuçlarda da hedef genelde kr.text
  // içinde tekrarlanmaz — baseline/target metnini pill'den TAMAMEN
  // düşürmek bilgi kaybına yol açar, bu yüzden metrik + aralık burada
  // da (bar olmadan) gösterilir; yalnız ikisi de boşsa sessiz kalınır.
  const hasRange = Boolean(kr.baseline) && Boolean(kr.target);

  return (
    <li className="bg-muted/40 rounded-xl border p-3">
      <p className="line-clamp-2 text-sm font-medium">{kr.text}</p>
      {hasNumbers ? (
        <>
          <KeyResultBar baseline={baselineNum} target={targetNum} />
          <p className="text-muted-foreground mt-1.5 text-xs">
            {kr.metric} · {t("dashboard.strategy.okr.baseline")} {kr.baseline} →{" "}
            {t("dashboard.strategy.okr.target")} {kr.target}
          </p>
        </>
      ) : kr.metric || hasRange ? (
        <Badge variant="outline" className="mt-2 text-[10px] font-normal">
          {kr.metric && hasRange
            ? `${kr.metric}: ${kr.baseline} → ${kr.target}`
            : hasRange
              ? `${kr.baseline} → ${kr.target}`
              : kr.metric}
        </Badge>
      ) : null}
    </li>
  );
}

/** İnce yatay ölçek çubuğu — "mevcut" (baseline) ile "hedef" (target)
 *  arasındaki farkı gösterir. Bilinçli olarak bir "% tamamlandı" iddiası
 *  DEĞİL (rapor taze üretilir, gerçek zamanlı ilerleme verisi yok) —
 *  yalnız iki değerin ortak bir eksende nerede durduğunu gösteren nötr
 *  bir ölçek (SharePill/ShareBar'daki "yanıltıcı yüzde gösterme"
 *  ilkesiyle aynı temkin). Hedef noktası dolgu nokta, aradaki mesafe
 *  soluk bir şerit; mount'ta soldan dolar (ShareBar ile aynı desen). */
function KeyResultBar({ baseline, target }: { baseline: number; target: number }) {
  const mounted = useMounted();
  const scaleMax = Math.max(Math.abs(baseline), Math.abs(target)) || 1;
  const basePct = Math.max(0, Math.min(100, (Math.abs(baseline) / scaleMax) * 100));
  const targetPct = Math.max(0, Math.min(100, (Math.abs(target) / scaleMax) * 100));
  const lo = Math.min(basePct, targetPct);
  const hi = Math.max(basePct, targetPct);
  // overflow-hidden BİLEREK yok — dolgu şerit zaten kendi rounded-full
  // sınırları içinde kalıyor (genişlik <= %100), ama hedef nokta uç
  // noktalarda (%0 / %100) -translate-x-1/2 ile kendi çapının yarısı
  // dışarı taşar; kırpma açık olsaydı o durumda yarım nokta görünürdü.
  return (
    <div className="bg-muted relative mt-2 h-1.5 w-full rounded-full" aria-hidden>
      <div
        className="bg-primary/25 absolute inset-y-0 rounded-full transition-[left,width] duration-700 [transition-timing-function:var(--motion-ease)]"
        style={{ left: mounted ? `${lo}%` : `${hi}%`, width: mounted ? `${hi - lo}%` : "0%" }}
      />
      <div
        className="bg-primary absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full transition-[left] duration-700 [transition-timing-function:var(--motion-ease)]"
        style={{ left: mounted ? `${targetPct}%` : `${basePct}%` }}
      />
    </div>
  );
}
