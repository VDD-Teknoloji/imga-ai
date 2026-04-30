"use client";

import type { LucideIcon } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";

interface MetricCardProps {
  title: string;
  value: number | undefined;
  isLoading: boolean;
  isError: boolean;
  hint?: string;
  icon: LucideIcon;
  /** Tailwind text colour utility for the icon container; falls back
   * to text-muted-foreground when omitted. */
  iconClassName?: string;
}

/**
 * Single metric tile. Three states:
 *
 *   - Loading    → skeleton bar in place of the number
 *   - Error      → "—" plus a muted error hint
 *   - Loaded     → big number + optional small hint underneath
 *
 * Empty data is loaded-with-zero, NOT a separate state — a fresh
 * tenant with no tickets sees "0" rather than "Veri yok" because
 * the absolute count is meaningful.
 */
export function MetricCard({
  title,
  value,
  isLoading,
  isError,
  hint,
  icon: Icon,
  iconClassName,
}: MetricCardProps) {
  return (
    <div className="bg-card flex flex-col gap-2 rounded-lg border p-5">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground text-sm font-medium">{title}</span>
        <Icon className={iconClassName ?? "text-muted-foreground size-4"} aria-hidden />
      </div>
      <div>
        {isLoading ? (
          <Skeleton className="h-9 w-16" />
        ) : isError ? (
          <span className="text-muted-foreground text-3xl font-semibold tracking-tight">—</span>
        ) : (
          <span className="text-3xl font-semibold tracking-tight">{value ?? 0}</span>
        )}
      </div>
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
      {isError ? (
        <p className="text-destructive text-xs">Veri yüklenemedi.</p>
      ) : null}
    </div>
  );
}
