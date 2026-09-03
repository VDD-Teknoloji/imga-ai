"use client";

// 2026-09-03 redesign — geçmiş özetler, kompakt satır listesi.
//
// Eski sürüm Card + CardHeader/CardTitle sarmalıyordu, her satırda
// ayrı bir "Görüntüle" butonu vardı. Yeni sürüm ana sayfanın
// rise-in/shadow-soft kart dilini kullanır; satırın KENDİSİ buton
// (advisor notu) — seçili satır aria-current + soft tint ile
// vurgulanır, ayrı bir trailing link'e gerek kalmaz. Davranış AYNI:
// tıklama yalnız `briefing_id`'yi URL'e yazar (page.tsx'teki
// pushParam({ briefing_id: b.id }) çağrısı buraya prop olarak akar).

import { FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { useTranslation } from "@/lib/i18n/use-translation";
import { BRIEFING_PERIOD_LABELS, type BriefingListItem } from "@/lib/types";
import { formatDateTr } from "@/lib/relative-time";

interface Props {
  items: BriefingListItem[];
  isLoading: boolean;
  selectedId: string;
  onSelect: (id: string) => void;
}

export function BriefingHistory({ items, isLoading, selectedId, onSelect }: Props) {
  const { t } = useTranslation();
  return (
    <div className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-5 ring-1 md:p-6">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold">
        <FileText className="text-muted-foreground size-4 shrink-0" aria-hidden />
        {t("briefing.history.title")}
      </h2>
      {isLoading ? (
        <p className="text-muted-foreground mt-3 text-sm">{t("briefing.history.loading")}</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground mt-3 text-sm">{t("briefing.history.empty")}</p>
      ) : (
        <ul className="mt-3 divide-y">
          {items.map((b) => {
            const selected = b.id === selectedId;
            return (
              <li key={b.id}>
                <button
                  type="button"
                  onClick={() => onSelect(b.id)}
                  aria-current={selected ? "true" : undefined}
                  aria-label={
                    selected
                      ? t("briefing.history.selectedAria")
                      : t("briefing.history.viewAria", { headline: b.headline })
                  }
                  className={`flex w-full flex-wrap items-center gap-3 rounded-xl px-2 py-2.5 text-left transition-colors ${
                    selected ? "bg-primary/8" : "hover:bg-muted/60"
                  }`}
                >
                  <Badge variant="outline" className="shrink-0">
                    {t(`briefing.period.${b.period}`) || BRIEFING_PERIOD_LABELS[b.period]}
                  </Badge>
                  <span className="text-muted-foreground shrink-0 text-xs" title={b.generated_at}>
                    {formatDateTr(b.generated_at)}
                  </span>
                  <p className="min-w-0 flex-1 truncate text-sm">{b.headline}</p>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
