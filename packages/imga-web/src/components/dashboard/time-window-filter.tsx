"use client";

// Sprint 13 — ana sayfa dönem filtresi (ürün sahibi isteği:
// "altta zaman bazlı filtreleme olsun 3 ay 6 ay").
//
// Hero + NPS + kategori chart'larının veri penceresini seçer.
// State URL'de yaşar (?window=3m|6m) — Path B mirror sayfada,
// bu bileşen saf controlled segmented-control.

import { useTranslation } from "@/lib/i18n/use-translation";
import { cn } from "@/lib/utils";

export type TimeWindowKey = "3m" | "6m" | "all";

const WINDOW_MONTHS: Record<TimeWindowKey, number | null> = {
  "3m": 3,
  "6m": 6,
  all: null,
};

export const TIME_WINDOW_KEYS: readonly TimeWindowKey[] = ["3m", "6m", "all"];

export function isTimeWindowKey(value: string | null): value is TimeWindowKey {
  return value === "3m" || value === "6m" || value === "all";
}

/** Pencerenin başlangıcı, YYYY-MM-DD (yerel). "all" için undefined —
 *  analytics hook'ları filtresiz sorgu atar. */
export function timeWindowDateFrom(key: TimeWindowKey): string | undefined {
  const months = WINDOW_MONTHS[key];
  if (months === null) return undefined;
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const LABEL_KEYS: Record<TimeWindowKey, string> = {
  "3m": "dashboard.window.3m",
  "6m": "dashboard.window.6m",
  all: "dashboard.window.all",
};

interface Props {
  value: TimeWindowKey;
  onChange: (next: TimeWindowKey) => void;
}

export function TimeWindowFilter({ value, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <div
      className="rise-in flex flex-wrap items-center gap-3"
      role="group"
      aria-label={t("dashboard.window.label")}
    >
      <span className="text-muted-foreground text-sm font-medium">
        {t("dashboard.window.label")}
      </span>
      <div className="bg-muted inline-flex rounded-full p-1">
        {TIME_WINDOW_KEYS.map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={value === key}
            onClick={() => onChange(key)}
            className={cn(
              "rounded-full px-4 py-1.5 text-sm font-medium transition-colors",
              value === key
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(LABEL_KEYS[key])}
          </button>
        ))}
      </div>
    </div>
  );
}
