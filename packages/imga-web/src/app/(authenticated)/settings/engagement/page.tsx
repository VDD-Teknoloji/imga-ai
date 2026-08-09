"use client";

// /settings/engagement — Katılım Oranı.
//
// Kurum bir ayda kaç işlem yaptığını girer; sistem o ayın yorum
// sayısını yorumun kendi tarihine göre sayıp katılım oranını
// (yorum / işlem) hesaplar ve kuruma tanımlı bantlara göre
// değerlendirir. Bantları yalnızca IMGA (süper yönetici) düzenler —
// eşiğin "iyi" mi "kötü" mü olduğu sektöre bağlı bir yargı.
//
// Filtre yok: pencere sabit son 12 ay. URL-state kuralı bu yüzden
// devreye girmiyor; tarih aralığı eklenirse Suspense + Path B mirror
// deseni zorunlu olur.

import { Download, Percent, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  type EngagementRow,
  useDeleteMonthlyMetric,
  useEngagement,
  useUpsertMonthlyMetric,
} from "@/hooks/use-engagement";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { formatApiErrorMessage } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

export default function EngagementPage() {
  const { t } = useTranslation();
  const { canWrite } = useRoleFlags();
  const engagement = useEngagement();

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Percent className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("settings.engagement.title")}
          </h1>
          <p className="text-muted-foreground text-sm">{t("settings.engagement.subtitle")}</p>
        </div>
      </header>

      {canWrite ? <EntryForm /> : null}

      {engagement.isLoading ? (
        <Skeleton className="h-72" />
      ) : engagement.isError ? (
        <p className="text-destructive text-sm">{t("settings.engagement.loadError")}</p>
      ) : engagement.data ? (
        <>
          <BandLegend bands={engagement.data.bands} />
          <EngagementTable rows={engagement.data.rows} canWrite={canWrite} />
        </>
      ) : null}
    </main>
  );
}

function BandLegend({ bands }: { bands: { min_pct: number; label: string }[] }) {
  const { t } = useTranslation();
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <h2 className="text-sm font-semibold">{t("settings.engagement.bands.title")}</h2>
        <p className="text-muted-foreground text-xs">
          {t("settings.engagement.bands.managedByImga")}
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          {bands.map((band, index) => (
            <Badge key={band.label} variant="outline" className="text-xs">
              {formatBandRange(band.min_pct, bands[index + 1]?.min_pct)} · {band.label}
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function EngagementTable({ rows, canWrite }: { rows: EngagementRow[]; canWrite: boolean }) {
  const { t } = useTranslation();
  const del = useDeleteMonthlyMetric();

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => downloadCsv(rows, t("settings.engagement.csv.header"))}
        >
          <Download className="size-3.5" aria-hidden />
          {t("settings.engagement.csv.download")}
        </Button>
      </div>
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("settings.engagement.col.month")}</TableHead>
              <TableHead className="text-right">
                {t("settings.engagement.col.transactions")}
              </TableHead>
              <TableHead className="text-right">{t("settings.engagement.col.reviews")}</TableHead>
              <TableHead className="text-right">{t("settings.engagement.col.pct")}</TableHead>
              <TableHead>{t("settings.engagement.col.rating")}</TableHead>
              {canWrite ? (
                <TableHead className="text-right">{t("settings.engagement.col.actions")}</TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.period_month}>
                <TableCell className="font-medium">{formatMonth(row.period_month)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.transaction_count === null ? (
                    <span className="text-muted-foreground text-xs">
                      {t("settings.engagement.noData")}
                    </span>
                  ) : (
                    row.transaction_count.toLocaleString("tr-TR")
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.review_count.toLocaleString("tr-TR")}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatPct(row.engagement_pct)}
                </TableCell>
                <TableCell>
                  {row.band_label ? (
                    <Badge variant="secondary" className="text-xs">
                      {row.band_label}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </TableCell>
                {canWrite ? (
                  <TableCell className="text-right">
                    {row.transaction_count === null ? null : (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={del.isPending}
                        className="gap-1 text-red-700 hover:text-red-900"
                        onClick={() => {
                          if (!confirm(t("settings.engagement.deleteConfirm"))) return;
                          del.mutate(row.period_month, {
                            onSuccess: () => toast.success(t("settings.engagement.deleted")),
                            onError: (err) => toast.error(formatApiErrorMessage(err)),
                          });
                        }}
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                        <span className="hidden sm:inline">{t("settings.common.delete")}</span>
                      </Button>
                    )}
                  </TableCell>
                ) : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function EntryForm() {
  const { t } = useTranslation();
  const upsert = useUpsertMonthlyMetric();
  const [month, setMonth] = useState<string>(currentMonthValue());
  const [count, setCount] = useState<string>("");
  const [notes, setNotes] = useState<string>("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const numeric = Number(count);
    if (!Number.isInteger(numeric) || numeric < 0) {
      toast.error(t("settings.engagement.countMustBeInteger"));
      return;
    }
    upsert.mutate(
      {
        // <input type="month"> "YYYY-MM" verir; backend ayın ilk gününü
        // bekler (zaten normalize eder, yine de doğru gönderiyoruz).
        period_month: `${month}-01`,
        transaction_count: numeric,
        notes: notes || null,
      },
      {
        onSuccess: () => {
          toast.success(t("settings.engagement.saved"));
          setCount("");
          setNotes("");
        },
        onError: (err) => toast.error(formatApiErrorMessage(err)),
      },
    );
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">{t("settings.engagement.form.title")}</h2>
        <p className="text-muted-foreground text-xs">{t("settings.engagement.form.help")}</p>
        <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1">
            <Label className="text-xs" htmlFor="engagement-month">
              {t("settings.engagement.form.month")}
            </Label>
            <Input
              id="engagement-month"
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs" htmlFor="engagement-count">
              {t("settings.engagement.form.transactions")}
            </Label>
            <Input
              id="engagement-count"
              type="number"
              min={0}
              step={1}
              value={count}
              onChange={(e) => setCount(e.target.value)}
              placeholder="100000"
              required
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs" htmlFor="engagement-notes">
              {t("settings.engagement.form.notes")}
            </Label>
            <Input
              id="engagement-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={1024}
              placeholder={t("settings.engagement.form.notesPlaceholder")}
            />
          </div>
          <Button type="submit" disabled={upsert.isPending} className="md:col-span-3">
            {upsert.isPending ? t("settings.common.saving") : t("settings.engagement.form.submit")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function formatMonth(iso: string): string {
  // ISO tarihini yerel saate çevirmeden okuruz: "2026-05-01" bazı
  // saat dilimlerinde bir gün geriye kayıp Nisan'a düşebilirdi.
  const [year, month] = iso.split("-");
  const date = new Date(Number(year), Number(month) - 1, 1);
  return date.toLocaleDateString("tr-TR", { year: "numeric", month: "long" });
}

function formatPct(pct: number | null): string {
  if (pct === null) return "—";
  return `%${pct.toLocaleString("tr-TR", { maximumFractionDigits: 2 })}`;
}

function formatBandRange(minPct: number, nextMinPct: number | undefined): string {
  if (nextMinPct === undefined) return `≥ %${minPct}`;
  return `%${minPct} – %${nextMinPct}`;
}

function currentMonthValue(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function downloadCsv(rows: EngagementRow[], header: string): void {
  const lines = [header];
  for (const row of rows) {
    lines.push(
      [
        row.period_month,
        row.transaction_count ?? "",
        row.review_count,
        row.engagement_pct ?? "",
        row.band_label ?? "",
      ]
        .map(csvCell)
        .join(";"),
    );
  }
  // BOM: Excel UTF-8'i ancak BOM ile tanıyor, yoksa Türkçe karakterler
  // bozuk açılıyor. Ayraç ";" — TR yerelinde Excel'in beklediği ayraç.
  const blob = new Blob(["﻿" + lines.join("\r\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "imga-katilim-orani.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value: string | number): string {
  const text = String(value);
  return /[";\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
