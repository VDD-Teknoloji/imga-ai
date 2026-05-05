"use client";

// Sprint 8.3.11 — batch picker for /reviews + /strategy.
//
// /reviews and /tenants/me/analyze/batch already accepted ``batch_id``
// filter from Sprint 8.3.5; the missing piece was a UI affordance to
// pick a batch from a dropdown rather than via deep link only.

import { Loader2 } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useBatchHistory } from "@/hooks/use-batch-uploads";
import type { BatchJob } from "@/lib/types";

interface Props {
  selected: string | undefined;
  onChange: (next: string | undefined) => void;
  /** When true, the trigger label reads "Yükleme: …" so the dropdown
   *  reads naturally inline alongside other filter pills. */
  inline?: boolean;
}

export function BatchFilterDropdown({ selected, onChange, inline }: Props) {
  const history = useBatchHistory(50);
  const jobs: BatchJob[] = history.data?.pages.flatMap((p) => p.jobs) ?? [];

  return (
    <Select
      value={selected || "__all__"}
      onValueChange={(v) =>
        onChange(v === "__all__" || v === null ? undefined : v ?? undefined)
      }
    >
      <SelectTrigger className="h-8 max-w-[280px] gap-1 text-xs">
        {history.isLoading ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : null}
        <SelectValue placeholder={inline ? "Yükleme: Tümü" : "Yükleme seç"} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="__all__">
          {inline ? "Yükleme: Tümü" : "Tümü"}
        </SelectItem>
        {jobs.map((j) => (
          <SelectItem key={j.job_id} value={j.job_id}>
            {formatJobLabel(j)}
          </SelectItem>
        ))}
        {!history.isLoading && jobs.length === 0 && (
          <SelectItem value="__none__" disabled>
            (Henüz yükleme yok)
          </SelectItem>
        )}
      </SelectContent>
    </Select>
  );
}

function formatJobLabel(job: BatchJob): string {
  const date = new Date(job.created_at).toLocaleDateString("tr-TR");
  const name = job.file_name.length > 40
    ? job.file_name.slice(0, 37) + "…"
    : job.file_name;
  return `${date} · ${name}`;
}
