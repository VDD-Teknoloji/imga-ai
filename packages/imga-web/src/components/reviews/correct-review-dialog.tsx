"use client";

// Sprint 11.0 — "Kararı Düzelt" dialog'u.
//
// Eski sistemin "Train & Save"inin modern hali: analist yanlış model
// kararını düzeltir; karar ANINDA güncellenir ve düzeltme üç katmanda
// "öğrenir" — birebir aynı metin bir daha gelirse düzeltilmiş karar
// uygulanır; benzer yorumlar için Gemini sınıflandırma prompt'una
// few-shot örneği olarak girer; embedding kaydedildiyse anlamsal
// komşu aramasına (RAG) katılır. Dialog bunu kullanıcıya tek
// cümleyle anlatır — "düzeltmeniz benzer yorumlara da öğretilecek".
//
// WS3 (2026-08-18, migration 0042): skor/deneyim/alt-kategori de
// duygu ve kategoriden BAĞIMSIZ düzeltilebilir hale geldi. Skor alanı
// mevcut satır skoruyla ön dolu gelir ve yalnız kullanıcı SLIDER/SAYI
// alanına doğrudan dokunursa gönderilir (dirty-check) — aksi halde
// backend'in SCORE_FOR_LABEL geri düşüşü çalışır. Duygu seçimi
// değişince skor öneriyi bandın ortasına günceller (aynı
// SCORE_FOR_LABEL sabitleri, correction_service.py ile birebir) ama
// kullanıcının elle girdiği değeri EZMEZ.

import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCategories } from "@/hooks/use-categories";
import { useCorrectReview } from "@/hooks/use-reviews";
import { useCompanyTaxonomies } from "@/hooks/use-taxonomies";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import { sentimentScoreBucket } from "@/lib/sentiment-score";

const SENTIMENTS = [
  { value: "POZITIF", label: "Pozitif" },
  { value: "NÖTR", label: "Nötr" },
  { value: "NEGATIF", label: "Negatif" },
] as const;

type SentimentValue = (typeof SENTIMENTS)[number]["value"];

// correction_service.py SCORE_FOR_LABEL ile birebir aynı sabitler —
// duygu değişince önerilen skor bunlara "band ortası" olarak düşer.
// Değerler kayarsa (imga-core config.py KB_POSITIVE_SCORE/
// KB_NEGATIVE_SCORE) burada da güncellenmeli.
const SCORE_FOR_LABEL: Record<SentimentValue, number> = {
  POZITIF: 0.9,
  NEGATIF: -0.9,
  NÖTR: 0.0,
};

/** Select'lerde "değiştirme" seçeneği için sentinel — backend'e
 *  gönderilmez (dirty-check bu değeri filtreler). */
const NO_CHANGE = "__no_change__";

function clampScore(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(-1, Math.min(1, value));
}

interface Props {
  reviewId: string;
  currentSentiment: string;
  currentCategory: string;
  /** WS3 — satırın güncel skoru/deneyim tipi/alt-kategori kodu. Dialog
   *  bunlarla ön dolu açılır; hiçbiri zorunlu değil (eski satırlarda
   *  deneyim/perspektif null olabilir). */
  currentScore?: number;
  currentExperienceType?: string | null;
  currentPerspectiveCode?: string | null;
}

export function CorrectReviewDialog({
  reviewId,
  currentSentiment,
  currentCategory,
  currentScore,
  currentExperienceType = null,
  currentPerspectiveCode = null,
}: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [sentiment, setSentiment] = useState<SentimentValue>(
    (SENTIMENTS.find((s) => s.value === currentSentiment)?.value ?? "NÖTR") as SentimentValue,
  );
  const [category, setCategory] = useState(currentCategory);
  const [reason, setReason] = useState("");

  // WS3 — skor: ön dolu, yalnız doğrudan dokunulursa "dirty" (bkz.
  // dosya başı yorum). Prop yoksa (beklenmedik durum) mevcut duyguya
  // göre SCORE_FOR_LABEL fallback'iyle başlar.
  const [score, setScore] = useState<number>(currentScore ?? SCORE_FOR_LABEL[sentiment]);
  const [scoreDirty, setScoreDirty] = useState(false);
  // 2026-09-03 (ürün sahibi) — skor "ince ayar" katlanır bölümde,
  // varsayılan kapalı: kategori/deneyim düzeltmesi skordan bağımsız,
  // ekran "önce skoru değiştir" gibi okunmasın.
  const [scoreOpen, setScoreOpen] = useState(false);

  // WS3 — deneyim + alt kategori: tri-state (Dijital/Operasyonel/—).
  const [experience, setExperience] = useState<string>(currentExperienceType ?? NO_CHANGE);
  const [perspective, setPerspective] = useState<string>(currentPerspectiveCode ?? NO_CHANGE);

  const categories = useCategories();
  const taxonomies = useCompanyTaxonomies();
  const correct = useCorrectReview();

  function handleSentimentChange(next: SentimentValue) {
    setSentiment(next);
    // Kullanıcı skoru elle değiştirmediyse öneriyi bandın ortasına
    // taşı; elle girilmiş değeri asla ezme.
    if (!scoreDirty) setScore(SCORE_FOR_LABEL[next]);
  }

  function handleScoreChange(next: number) {
    setScore(clampScore(next));
    setScoreDirty(true);
  }

  const sentimentChanged = sentiment !== currentSentiment;
  const categoryChanged = category !== currentCategory;
  const experienceInitial = currentExperienceType ?? NO_CHANGE;
  const experienceChanged = experience !== NO_CHANGE && experience !== experienceInitial;
  const perspectiveInitial = currentPerspectiveCode ?? NO_CHANGE;
  const perspectiveChanged = perspective !== NO_CHANGE && perspective !== perspectiveInitial;

  const unchanged =
    !sentimentChanged &&
    !categoryChanged &&
    !scoreDirty &&
    !experienceChanged &&
    !perspectiveChanged;
  const changedFields = [
    sentimentChanged ? t("reviews.correct.field.sentiment") : null,
    scoreDirty ? t("reviews.correct.scoreLabel") : null,
    categoryChanged ? t("reviews.correct.field.category") : null,
    experienceChanged ? t("reviews.correct.experienceLabel") : null,
    perspectiveChanged ? t("reviews.correct.subcategoryLabel") : null,
  ].filter((x): x is string => x !== null);
  const currentSentimentLabel =
    SENTIMENTS.find((s) => s.value === currentSentiment)?.label ?? currentSentiment;
  const currentCategoryLabel =
    (categories.data ?? []).find((c) => c.code === currentCategory)?.label_tr ?? currentCategory;
  const currentExperienceLabel =
    currentExperienceType === null
      ? t("reviews.correct.unassigned")
      : t(`reviews.experience.${currentExperienceType}`);
  const currentPerspectiveLabel =
    currentPerspectiveCode === null
      ? t("reviews.correct.unassigned")
      : ((taxonomies.data ?? []).find((x) => x.code === currentPerspectiveCode)?.label_tr ??
        currentPerspectiveCode);

  function handleSubmit() {
    correct.mutate(
      {
        reviewId,
        sentiment_label: sentimentChanged ? sentiment : undefined,
        primary_category: categoryChanged ? category : undefined,
        sentiment_score: scoreDirty ? score : undefined,
        experience_type: experienceChanged ? (experience as "dijital" | "operasyonel") : undefined,
        perspective_code: perspectiveChanged ? perspective : undefined,
        reason: reason.trim() || undefined,
      },
      {
        onSuccess: (data) => {
          toast.success(
            data.embedding_stored
              ? "Düzeltme kaydedildi — benzer yorumlara da öğretilecek."
              : "Düzeltme kaydedildi ve birebir eşleşmelerde uygulanacak.",
          );
          setOpen(false);
          setReason("");
          // Yanıt otoriter değerleri taşır — sonraki açılışta dialog
          // güncel duruma göre başlasın diye local state senkronize
          // edilir (dialog kapanınca unmount olmuyor, bkz. dosya başı).
          setSentiment(data.sentiment_label as SentimentValue);
          setCategory(data.primary_category);
          setScore(data.sentiment_score);
          setScoreDirty(false);
          setExperience(data.experience_type ?? NO_CHANGE);
          setPerspective(data.perspective_code ?? NO_CHANGE);
        },
        onError: (err) => {
          toast.error(err instanceof ApiError ? err.detail : "Düzeltme kaydedilemedi.");
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant="outline" className="gap-2">
            <Sparkles className="size-4" aria-hidden />
            Kararı Düzelt
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Model kararını düzelt</DialogTitle>
          <DialogDescription>{t("reviews.correct.description")}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto py-2">
          <div className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <Label>{t("reviews.correct.field.sentiment")}</Label>
              <span className="text-muted-foreground text-xs">
                {t("reviews.correct.current", { value: currentSentimentLabel })}
              </span>
            </div>
            <Select
              value={sentiment}
              onValueChange={(v) => v && handleSentimentChange(v as SentimentValue)}
            >
              <SelectTrigger>
                {/* base-ui SelectValue çocuk verilmezse HAM değeri basar
                    (NEGATIF, kargo, __no_change__...) — dört tetikleyici
                    de etikete eşlenir. */}
                <SelectValue>
                  {(v: string) => SENTIMENTS.find((s) => s.value === v)?.label ?? v}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {SENTIMENTS.map((s) => (
                  <SelectItem key={s.value} value={s.value}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setScoreOpen((v) => !v)}
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs font-medium"
              aria-expanded={scoreOpen}
            >
              {scoreOpen ? (
                <ChevronDown className="size-3.5" aria-hidden />
              ) : (
                <ChevronRight className="size-3.5" aria-hidden />
              )}
              {t("reviews.correct.scoreToggle")}
              <span className="font-normal">
                {" "}
                · {score.toFixed(2)} ({t(`reviews.scoreLabel.${sentimentScoreBucket(score)}`)})
              </span>
            </button>
            {scoreOpen && (
              <div className="space-y-2 pl-4">
                <div className="flex items-center gap-3">
                  <input
                    id="correction-score"
                    type="range"
                    min={-1}
                    max={1}
                    step={0.05}
                    value={score}
                    aria-label={t("reviews.correct.scoreSliderAria")}
                    onChange={(e) => handleScoreChange(Number(e.target.value))}
                    className="accent-primary h-2 flex-1 cursor-pointer"
                  />
                  <input
                    type="number"
                    min={-1}
                    max={1}
                    step={0.05}
                    value={score}
                    aria-label={t("reviews.correct.scoreNumberAria")}
                    onChange={(e) => handleScoreChange(Number(e.target.value))}
                    className="border-input focus-visible:border-ring focus-visible:ring-ring/50 h-8 w-20 rounded-lg border bg-transparent px-2 text-sm tabular-nums outline-none focus-visible:ring-3"
                  />
                  {/* Kaydırıcı/sayı ile canlı güncellenen kova etiketi —
                  "çok olumsuz" gibi yazılar kullanıcının ne girdiğini
                  anında anlamasını sağlar. */}
                  <Badge variant="outline" className="shrink-0">
                    {t(`reviews.scoreLabel.${sentimentScoreBucket(score)}`)}
                  </Badge>
                </div>
                <p className="text-muted-foreground text-xs">{t("reviews.correct.scoreHint")}</p>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <Label>{t("reviews.correct.field.category")}</Label>
              <span className="text-muted-foreground text-xs">
                {t("reviews.correct.current", { value: currentCategoryLabel })}
              </span>
            </div>
            <Select value={category} onValueChange={(v) => v && setCategory(v)}>
              <SelectTrigger>
                <SelectValue>
                  {(v: string) => (categories.data ?? []).find((c) => c.code === v)?.label_tr ?? v}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(categories.data ?? [])
                  .filter((c) => c.is_enabled && !c.is_archived)
                  .map((c) => (
                    <SelectItem key={c.code} value={c.code}>
                      {c.label_tr}
                    </SelectItem>
                  ))}
                {/* Mevcut kategori listede yoksa (arşivlenmiş vb.)
                    yine seçilebilir kalsın. */}
                {!(categories.data ?? []).some((c) => c.code === currentCategory) && (
                  <SelectItem value={currentCategory}>{currentCategory}</SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <Label htmlFor="correction-experience">{t("reviews.correct.experienceLabel")}</Label>
              <span className="text-muted-foreground text-xs">
                {t("reviews.correct.current", { value: currentExperienceLabel })}
              </span>
            </div>
            <Select value={experience} onValueChange={(v) => v && setExperience(v)}>
              <SelectTrigger id="correction-experience" className="w-full">
                <SelectValue>
                  {(v: string) =>
                    v === NO_CHANGE ? t("reviews.correct.noChange") : t(`reviews.experience.${v}`)
                  }
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_CHANGE}>{t("reviews.correct.noChange")}</SelectItem>
                <SelectItem value="dijital">{t("reviews.experience.dijital")}</SelectItem>
                <SelectItem value="operasyonel">{t("reviews.experience.operasyonel")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <Label htmlFor="correction-perspective">
                {t("reviews.correct.subcategoryLabel")}
              </Label>
              <span className="text-muted-foreground text-xs">
                {t("reviews.correct.current", { value: currentPerspectiveLabel })}
              </span>
            </div>
            <Select value={perspective} onValueChange={(v) => v && setPerspective(v)}>
              <SelectTrigger id="correction-perspective" className="w-full">
                <SelectValue>
                  {(v: string) =>
                    v === NO_CHANGE
                      ? t("reviews.correct.noChange")
                      : ((taxonomies.data ?? []).find((x) => x.code === v)?.label_tr ?? v)
                  }
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_CHANGE}>{t("reviews.correct.noChange")}</SelectItem>
                {(taxonomies.data ?? []).map((tax) => (
                  <SelectItem key={tax.code} value={tax.code}>
                    {tax.label_tr}
                  </SelectItem>
                ))}
                {!taxonomies.isLoading && (taxonomies.data ?? []).length === 0 && (
                  <SelectItem value="__no_taxonomy__" disabled>
                    {t("reviews.perspFilter.noTaxonomy")}
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="correction-reason">Gerekçe (opsiyonel)</Label>
            <Textarea
              id="correction-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Örn: İroni var — müşteri aslında şikayet ediyor."
              rows={2}
            />
            <p className="text-muted-foreground text-xs">
              Gerekçe, yapay zekaya örnek olarak verilir ve benzer durumlarda kararı yönlendirir.
            </p>
          </div>
        </div>

        <DialogFooter className="items-center">
          <p className="text-muted-foreground mr-auto text-xs">
            {changedFields.length > 0
              ? t("reviews.correct.willChange", { fields: changedFields.join(", ") })
              : t("reviews.correct.nothingChanged")}
          </p>
          <Button variant="outline" type="button" onClick={() => setOpen(false)}>
            Vazgeç
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={unchanged || correct.isPending}
            title={unchanged ? t("reviews.correct.nothingChanged") : undefined}
          >
            {correct.isPending ? "Kaydediliyor…" : "Düzeltmeyi Kaydet"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
