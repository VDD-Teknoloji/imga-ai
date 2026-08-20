// Süper-admin özet kartı — 3 tonlu (nötr/ok/uyarı) kenarlık.
//
// /admin/llm-audit sayfasının yerel `SummaryCard`'ından çıkarıldı
// (C1 — 2026-08-20 süper-admin envanteri): /admin/usage platform
// kartları da aynı deseni paylaşıyor, iki kopya tutmak yerine tek
// bileşen.

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function AdminSummaryCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn";
}) {
  return (
    <Card
      className={cn(
        "border-2",
        tone === "warn"
          ? "border-amber-300"
          : tone === "ok"
            ? "border-emerald-300"
            : "border-zinc-200",
      )}
    >
      <CardContent className="space-y-1 p-3">
        <p className="text-muted-foreground text-xs">{label}</p>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}
