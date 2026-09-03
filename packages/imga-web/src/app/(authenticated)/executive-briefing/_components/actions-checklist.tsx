"use client";

// 2026-09-03 redesign — öncelikli aksiyonlar, checklist görünümü.
//
// Veri kaynağı ve mantığı DEĞİŞMEDİ: useBriefingTopActions linked
// ActionItem satırlarını tercih eder (tıklanabilir, durum farkında),
// bulamazsa (eski brifing, extraction log yok) ham `top_actions`
// metnine düşer — eski TopActionsSection'ın aynısı, yalnız görsel
// dil SquareCheck ikonlu checklist satırlarına taşındı (görev
// talimatı: "checklist-style list with a CheckSquare icon").

import Link from "next/link";
import { SquareCheck } from "lucide-react";

import { SectionHeading } from "@/components/dashboard/section-heading";
import { useBriefingTopActions } from "@/hooks/use-executive-briefings";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { BriefingTopAction } from "@/lib/types";

function ActionStatusBadge({
  status,
  priority,
}: {
  status: "open" | "in_progress" | "done" | "cancelled";
  priority: "high" | "medium" | "low";
}) {
  const { t } = useTranslation();
  const statusLabel: Record<typeof status, string> = {
    open: t("briefing.status.open"),
    in_progress: t("briefing.status.inProgress"),
    done: t("briefing.status.done"),
    cancelled: t("briefing.status.cancelled"),
  };
  const tone =
    status === "done"
      ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
      : status === "in_progress"
        ? "bg-blue-100 text-blue-900 dark:bg-blue-950/40 dark:text-blue-300"
        : status === "cancelled"
          ? "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
          : priority === "high"
            ? "bg-red-100 text-red-900 dark:bg-red-950/40 dark:text-red-300"
            : "bg-amber-100 text-amber-900 dark:bg-amber-950/40 dark:text-amber-300";
  return (
    <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${tone}`}>{statusLabel[status]}</span>
  );
}

export function ActionsChecklist({
  briefingId,
  fallback,
}: {
  briefingId: string;
  fallback: BriefingTopAction[];
}) {
  const { t } = useTranslation();
  const linked = useBriefingTopActions(briefingId);
  const hasLinked = (linked.data?.items?.length ?? 0) > 0;

  // Sessizlik kuralı: ne bağlı satır ne ham metin varsa bölüm çizilmez.
  if (!hasLinked && fallback.length === 0) return null;

  return (
    <section aria-label={t("briefing.actions.title")}>
      <SectionHeading title={t("briefing.actions.title")} icon={SquareCheck} />
      {hasLinked ? (
        <ul className="mt-4 space-y-2">
          {linked.data!.items.map((a, idx) => (
            <li key={a.id} className="rise-in" style={{ animationDelay: `${idx * 50}ms` }}>
              <Link
                href={`/action-items/${a.id}`}
                className="flex items-start gap-2.5 rounded-2xl border border-transparent bg-sky-500/10 p-3 transition-colors hover:bg-sky-500/15"
              >
                <SquareCheck
                  className="mt-0.5 size-4 shrink-0 text-sky-700 dark:text-sky-400"
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <p className="line-clamp-1 text-sm font-medium">{a.title}</p>
                    <ActionStatusBadge status={a.status} priority={a.priority} />
                  </div>
                  <p className="text-muted-foreground mt-1 line-clamp-1 text-xs">
                    {a.rationale ?? a.description}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <ul className="mt-4 space-y-2">
          {fallback.map((a, idx) => (
            <li
              key={idx}
              className="rise-in flex items-start gap-2.5 rounded-2xl bg-sky-500/10 p-3"
              style={{ animationDelay: `${idx * 50}ms` }}
            >
              <SquareCheck
                className="mt-0.5 size-4 shrink-0 text-sky-700 dark:text-sky-400"
                aria-hidden
              />
              <div className="min-w-0">
                <p className="line-clamp-1 text-sm font-medium">{a.title}</p>
                <p className="text-muted-foreground mt-1 line-clamp-1 text-xs">{a.rationale}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
