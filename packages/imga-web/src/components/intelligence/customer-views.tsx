"use client";

// /churn görünümleri (2026-10-14): "En kritik 100" tablosu, segment →
// müşteri ağaç haritası ve yolculuk aşaması → risk bandı → müşteri ağacı.
//
// Veri /tenants/me/intelligence/customers/critical ve /customers/map
// uçlarından gelir; puan "rules-v1" öncelik puanıdır, olasılık DEĞİL.
// Renk = risk bandı (durum rengi, her zaman etiketle birlikte); büyüklük
// = seçilen ölçü (puan ya da gelir). Kimlik rengi yok, tek eksen.

import { ResponsiveContainer, Treemap } from "recharts";
import type { TreemapNode } from "recharts/types/chart/Treemap";

import { JourneyStageBadge } from "@/components/journey-stage-badge";
import { Choice, Loading } from "@/components/intelligence/fields";
import { useTranslation } from "@/lib/i18n/use-translation";
import type {
  CriticalCustomers,
  CustomerMap,
  CustomerMapNode,
  CustomerRecord,
  RiskBand,
} from "@/lib/intelligence-types";
import { JOURNEY_STAGES, journeyLabelKey } from "@/lib/journey";

export const BAND_ORDER: RiskBand[] = ["critical", "high", "watch", "low", "unknown", "inactive"];

export const BAND_TEXT: Record<RiskBand, string> = {
  critical: "text-red-700 dark:text-red-400",
  high: "text-amber-700 dark:text-amber-400",
  watch: "text-sky-700 dark:text-sky-400",
  low: "text-emerald-700 dark:text-emerald-400",
  unknown: "text-muted-foreground",
  inactive: "text-muted-foreground",
};

// Durum paleti (dataviz: good/warning/serious/critical ayrı adımlar);
// bilinmeyen/pasif nötr gri. Kutu üstünde metin her zaman yazılı.
const BAND_FILL: Record<RiskBand, string> = {
  critical: "#dc2626",
  high: "#d97706",
  watch: "#0284c7",
  low: "#059669",
  unknown: "#94a3b8",
  inactive: "#cbd5e1",
};
const BAND_INK: Record<RiskBand, string> = {
  critical: "#ffffff",
  high: "#ffffff",
  watch: "#ffffff",
  low: "#ffffff",
  unknown: "#0f172a",
  inactive: "#0f172a",
};

export type SizeBy = "score" | "revenue";

function isBand(value: unknown): value is RiskBand {
  return typeof value === "string" && (BAND_ORDER as string[]).includes(value);
}

// ----------------------------------------------------------------- critical

export function CriticalCustomersView({
  data,
  isLoading,
  onOpen,
}: {
  data: CriticalCustomers | undefined;
  isLoading: boolean;
  onOpen: (record: CustomerRecord) => void;
}) {
  const { t, locale } = useTranslation();
  if (isLoading || !data) return <Loading />;
  const nf = new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR");
  const excludedParts = (
    [
      ["insufficient", "intel.excludedInsufficient"],
      ["stale", "intel.excludedStale"],
      ["inactive", "intel.excludedInactive"],
    ] as const
  )
    .filter(([key]) => (data.excluded[key] ?? 0) > 0)
    .map(([key, labelKey]) => `${nf.format(data.excluded[key] ?? 0)} ${t(labelKey)}`);
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">{t("intel.criticalIntro")}</p>
      <dl className="flex flex-wrap gap-6 border-y py-3 text-sm">
        <div>
          <dt className="text-muted-foreground text-xs">{t("intel.rankedTotal")}</dt>
          <dd className="font-semibold tabular-nums">
            {nf.format(data.ranked_total)} / {nf.format(data.account_count)}
          </dd>
        </div>
        {BAND_ORDER.filter((band) => (data.bands[band] ?? 0) > 0).map((band) => (
          <div key={band}>
            <dt className={`text-xs ${BAND_TEXT[band]}`}>{t(`intel.${band}`)}</dt>
            <dd className="font-semibold tabular-nums">{nf.format(data.bands[band] ?? 0)}</dd>
          </div>
        ))}
        {excludedParts.length > 0 ? (
          <div>
            <dt className="text-muted-foreground text-xs">{t("intel.excluded")}</dt>
            <dd className="text-muted-foreground">{excludedParts.join(" · ")}</dd>
          </div>
        ) : null}
      </dl>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[880px] text-left text-sm">
          <thead>
            <tr className="text-muted-foreground border-b">
              {[
                "rank",
                "name",
                "riskScore",
                "stage",
                "churnIntent",
                "reviews30d",
                "owner",
                "followUp",
                "outcome",
              ].map((key) => (
                <th key={key} scope="col" className="px-2 py-3 font-medium">
                  {t(`intel.${key}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.items.map((item, index) => {
              const signals = item.risk.review_signals;
              return (
                <tr key={item.profile.external_id} className="hover:bg-muted/40 border-b">
                  <td className="text-muted-foreground px-2 py-3 tabular-nums">{index + 1}</td>
                  <td className="max-w-64 px-2 py-3">
                    <button
                      type="button"
                      className="w-full text-left font-medium break-words underline-offset-4 hover:underline"
                      dir="auto"
                      onClick={() => onOpen(item)}
                    >
                      {item.profile.name}
                    </button>
                    <p className="text-muted-foreground text-xs break-all">
                      {item.profile.external_id}
                      {item.profile.segment ? ` · ${item.profile.segment}` : ""}
                    </p>
                  </td>
                  <td className={`px-2 py-3 ${BAND_TEXT[item.risk.band]}`}>
                    <strong className="tabular-nums">{item.risk.score ?? "-"}</strong>
                    <p className="text-xs">{t(`intel.${item.risk.band}`)}</p>
                  </td>
                  <td className="px-2 py-3">
                    <JourneyStageBadge stage={item.journey?.latest_stage} showUnassigned />
                  </td>
                  <td className="px-2 py-3 tabular-nums">
                    {item.journey && item.journey.churn_intent > 0 ? (
                      <span className="text-sentiment-negative font-semibold">
                        {nf.format(item.journey.churn_intent)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </td>
                  <td className="px-2 py-3 tabular-nums">
                    {signals.total > 0 ? (
                      <>
                        {nf.format(signals.total)}
                        <span className="text-muted-foreground text-xs">
                          {" "}
                          · {nf.format(signals.negative)} {t("intel.negativeShort")}
                        </span>
                      </>
                    ) : (
                      <span className="text-muted-foreground text-xs">
                        {t("intel.noLinkedReviews")}
                      </span>
                    )}
                  </td>
                  <td className="max-w-48 px-2 py-3 break-words">{item.profile.owner || "-"}</td>
                  <td className="px-2 py-3">{item.profile.follow_up_on || "-"}</td>
                  <td className="px-2 py-3">{t(`intel.${item.profile.outcome}`)}</td>
                </tr>
              );
            })}
            {!data.items.length && (
              <tr>
                <td colSpan={9} className="text-muted-foreground py-12 text-center">
                  {t("intel.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ treemap

interface TreemapLeaf {
  name: string;
  size: number;
  band: RiskBand;
  external_id: string;
  score: number | null;
  stage: string | null;
  segment: string;
  [key: string]: unknown;
}
interface TreemapGroup {
  name: string;
  children: TreemapLeaf[];
  [key: string]: unknown;
}

function nodeSize(node: CustomerMapNode, sizeBy: SizeBy): number {
  if (sizeBy === "revenue") {
    const revenue = node.annual_revenue === null ? 0 : Number(node.annual_revenue);
    return Number.isFinite(revenue) && revenue > 0 ? revenue : 0;
  }
  // Puan yoksa (yetersiz veri) küçük ama görünür bir kutu — "veri yok"
  // ile "risk yok" aynı görünmesin diye bant rengi gri kalır.
  return node.score === null ? 4 : Math.max(node.score, 4);
}

function TreemapContent(props: TreemapNode) {
  const { x, y, width, height, depth, name } = props;
  if (depth === 1) {
    return (
      <g>
        <rect
          x={x}
          y={y}
          width={width}
          height={height}
          fill="none"
          stroke="var(--border)"
          strokeWidth={2}
        />
      </g>
    );
  }
  if (depth !== 2) return <g />;
  const band = isBand(props.band) ? props.band : "unknown";
  const label = String(name);
  const score = typeof props.score === "number" ? props.score : null;
  const segment = typeof props.segment === "string" ? props.segment : "";
  const showLabel = width > 44 && height > 18;
  const showScore = width > 44 && height > 34 && score !== null;
  // Segment çerçevesi (depth 1) çocuklar tarafından örtüldüğü için grup
  // adı yaprağın içinde, puanın altında yazılır.
  const showSegment = width > 60 && height > 52 && segment !== "";
  return (
    <g style={{ cursor: "pointer" }}>
      <title>{`${label}${segment ? ` · ${segment}` : ""}${score === null ? "" : ` · ${score}`}`}</title>
      <rect
        x={x + 1}
        y={y + 1}
        width={Math.max(0, width - 2)}
        height={Math.max(0, height - 2)}
        rx={3}
        fill={BAND_FILL[band]}
        fillOpacity={0.88}
        stroke="var(--background)"
        strokeWidth={1}
      />
      {showLabel ? (
        <text
          x={x + 6}
          y={y + 15}
          fill={BAND_INK[band]}
          fontSize={11}
          style={{ pointerEvents: "none" }}
        >
          {label.slice(0, Math.max(2, Math.floor((width - 8) / 6.5)))}
        </text>
      ) : null}
      {showScore ? (
        <text
          x={x + 6}
          y={y + 29}
          fill={BAND_INK[band]}
          fontSize={11}
          fontWeight={700}
          style={{ pointerEvents: "none" }}
        >
          {score}
        </text>
      ) : null}
      {showSegment ? (
        <text
          x={x + 6}
          y={y + 44}
          fill={BAND_INK[band]}
          fillOpacity={0.85}
          fontSize={10}
          style={{ pointerEvents: "none" }}
        >
          {segment.slice(0, Math.max(2, Math.floor((width - 8) / 6)))}
        </text>
      ) : null}
    </g>
  );
}

export function CustomerTreemapView({
  data,
  isLoading,
  sizeBy,
  onSizeByChange,
  onSelect,
}: {
  data: CustomerMap | undefined;
  isLoading: boolean;
  sizeBy: SizeBy;
  onSizeByChange: (value: SizeBy) => void;
  onSelect: (externalId: string) => void;
}) {
  const { t, locale } = useTranslation();
  if (isLoading || !data) return <Loading />;
  const nf = new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR");
  const groups = new Map<string, TreemapLeaf[]>();
  let withoutRevenue = 0;
  for (const node of data.nodes) {
    const size = nodeSize(node, sizeBy);
    if (size <= 0) {
      withoutRevenue += 1;
      continue;
    }
    const key = node.segment || t("intel.noSegment");
    const bucket = groups.get(key) ?? [];
    bucket.push({
      name: node.name,
      size,
      band: node.band,
      external_id: node.external_id,
      score: node.score,
      stage: node.stage,
      segment: node.segment,
    });
    groups.set(key, bucket);
  }
  const treemapData: TreemapGroup[] = [...groups.entries()]
    .map(([name, children]) => ({
      name,
      children: children.sort((a, b) => b.size - a.size),
    }))
    .sort((a, b) => b.children.length - a.children.length);
  const bandCounts = BAND_ORDER.map((band) => ({
    band,
    count: data.nodes.filter((node) => node.band === band).length,
  })).filter((entry) => entry.count > 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="text-muted-foreground max-w-prose text-sm">{t("intel.mapIntro")}</p>
        <div className="w-44">
          <Choice
            label={t("intel.sizeBy")}
            value={sizeBy}
            options={[
              { value: "score", label: t("intel.sizeScore") },
              { value: "revenue", label: t("intel.sizeRevenue") },
            ]}
            onChange={(value) => onSizeByChange(value === "revenue" ? "revenue" : "score")}
          />
        </div>
      </div>
      {treemapData.length === 0 ? (
        <p className="text-muted-foreground py-12 text-center text-sm">{t("intel.mapEmpty")}</p>
      ) : (
        <div className="bg-card h-[420px] w-full rounded-lg border p-2 sm:h-[520px]">
          <ResponsiveContainer width="100%" height="100%">
            <Treemap
              data={treemapData}
              dataKey="size"
              nameKey="name"
              aspectRatio={4 / 3}
              isAnimationActive={false}
              content={TreemapContent}
              onClick={(node: TreemapNode) => {
                const id = node.external_id;
                if (typeof id === "string" && id) onSelect(id);
              }}
            />
          </ResponsiveContainer>
        </div>
      )}
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label={t("intel.band")}>
        {bandCounts.map(({ band, count }) => (
          <li key={band} className="flex items-center gap-1.5">
            <span
              className="inline-block size-3 rounded-sm"
              style={{ backgroundColor: BAND_FILL[band] }}
              aria-hidden
            />
            <span className={BAND_TEXT[band]}>{t(`intel.${band}`)}</span>
            <span className="text-muted-foreground tabular-nums">{nf.format(count)}</span>
          </li>
        ))}
      </ul>
      {sizeBy === "revenue" && withoutRevenue > 0 ? (
        <p className="text-muted-foreground text-xs">
          {t("intel.noRevenueNote", { count: nf.format(withoutRevenue) })}
        </p>
      ) : null}
      {data.truncated ? (
        <p className="text-muted-foreground text-xs">
          {t("intel.truncated", {
            limit: nf.format(data.nodes.length),
            total: nf.format(data.account_count),
          })}
        </p>
      ) : null}
    </div>
  );
}

// --------------------------------------------------------------------- tree

export function CustomerTreeView({
  data,
  isLoading,
  onSelect,
}: {
  data: CustomerMap | undefined;
  isLoading: boolean;
  onSelect: (externalId: string) => void;
}) {
  const { t, locale } = useTranslation();
  if (isLoading || !data) return <Loading />;
  const nf = new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR");
  if (data.nodes.length === 0) {
    return <p className="text-muted-foreground py-12 text-center text-sm">{t("intel.mapEmpty")}</p>;
  }
  const stageKeys: (string | null)[] = [...JOURNEY_STAGES, null];
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground max-w-prose text-sm">{t("intel.treeIntro")}</p>
      <p className="text-muted-foreground max-w-prose text-xs">{t("intel.linkHint")}</p>
      <ul className="space-y-2">
        {stageKeys.map((stage) => {
          const inStage = data.nodes.filter((node) => (node.stage ?? null) === stage);
          if (inStage.length === 0) return null;
          const bands = BAND_ORDER.map((band) => ({
            band,
            nodes: inStage.filter((node) => node.band === band),
          })).filter((entry) => entry.nodes.length > 0);
          const riskyCount = inStage.filter(
            (node) => node.band === "critical" || node.band === "high",
          ).length;
          return (
            <li key={stage ?? "atanmamis"} className="rounded-lg border">
              <details open={stage === "ayrilma"}>
                <summary className="flex cursor-pointer flex-wrap items-center gap-3 px-3 py-2.5">
                  <span className="font-medium">{t(journeyLabelKey(stage))}</span>
                  <span className="text-muted-foreground text-sm tabular-nums">
                    {t("intel.customersCount", { count: nf.format(inStage.length) })}
                  </span>
                  {riskyCount > 0 ? (
                    <span className={`text-sm tabular-nums ${BAND_TEXT.critical}`}>
                      {nf.format(riskyCount)} {t("intel.critical").toLowerCase()}/
                      {t("intel.high").toLowerCase()}
                    </span>
                  ) : null}
                </summary>
                <ul className="border-t">
                  {bands.map(({ band, nodes }) => (
                    <li key={band} className="border-b last:border-b-0">
                      <details open={band === "critical" || band === "high"}>
                        <summary className="flex cursor-pointer items-center gap-3 px-6 py-2">
                          <span
                            className="inline-block size-2.5 rounded-sm"
                            style={{ backgroundColor: BAND_FILL[band] }}
                            aria-hidden
                          />
                          <span className={`font-medium ${BAND_TEXT[band]}`}>
                            {t(`intel.${band}`)}
                          </span>
                          <span className="text-muted-foreground text-xs tabular-nums">
                            {t("intel.customersCount", { count: nf.format(nodes.length) })}
                          </span>
                        </summary>
                        <ul className="divide-y">
                          {nodes.map((node) => (
                            <li key={node.external_id}>
                              <button
                                type="button"
                                onClick={() => onSelect(node.external_id)}
                                className="hover:bg-muted/40 flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-9 py-2 text-left text-sm"
                                title={t("intel.openInList")}
                              >
                                <span className="min-w-40 font-medium break-words" dir="auto">
                                  {node.name}
                                </span>
                                <span className="text-muted-foreground text-xs break-all">
                                  {node.external_id}
                                  {node.segment ? ` · ${node.segment}` : ""}
                                </span>
                                <span className={`tabular-nums ${BAND_TEXT[node.band]}`}>
                                  {node.score ?? "-"}
                                </span>
                                {node.churn_intent > 0 ? (
                                  <span className="text-sentiment-negative text-xs">
                                    {t("intel.churnIntentCount", {
                                      count: nf.format(node.churn_intent),
                                    })}
                                  </span>
                                ) : null}
                                {node.reviews_30d > 0 ? (
                                  <span className="text-muted-foreground text-xs tabular-nums">
                                    {t("intel.reviews30d")}: {nf.format(node.reviews_30d)} ·{" "}
                                    {nf.format(node.negative_30d)} {t("intel.negativeShort")}
                                  </span>
                                ) : null}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </details>
                    </li>
                  ))}
                </ul>
              </details>
            </li>
          );
        })}
      </ul>
      {data.truncated ? (
        <p className="text-muted-foreground text-xs">
          {t("intel.truncated", {
            limit: nf.format(data.nodes.length),
            total: nf.format(data.account_count),
          })}
        </p>
      ) : null}
    </div>
  );
}
