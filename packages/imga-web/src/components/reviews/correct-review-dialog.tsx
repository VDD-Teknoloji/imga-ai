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

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { ApiError } from "@/lib/api-client";

const SENTIMENTS = [
  { value: "POZITIF", label: "Pozitif" },
  { value: "NÖTR", label: "Nötr" },
  { value: "NEGATIF", label: "Negatif" },
] as const;

type SentimentValue = (typeof SENTIMENTS)[number]["value"];

interface Props {
  reviewId: string;
  currentSentiment: string;
  currentCategory: string;
}

export function CorrectReviewDialog({
  reviewId,
  currentSentiment,
  currentCategory,
}: Props) {
  const [open, setOpen] = useState(false);
  const [sentiment, setSentiment] = useState<SentimentValue>(
    (SENTIMENTS.find((s) => s.value === currentSentiment)?.value ??
      "NÖTR") as SentimentValue,
  );
  const [category, setCategory] = useState(currentCategory);
  const [reason, setReason] = useState("");
  const categories = useCategories();
  const correct = useCorrectReview();

  const unchanged =
    sentiment === currentSentiment && category === currentCategory;

  function handleSubmit() {
    correct.mutate(
      {
        reviewId,
        sentiment_label:
          sentiment !== currentSentiment ? sentiment : undefined,
        primary_category:
          category !== currentCategory ? category : undefined,
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
        },
        onError: (err) => {
          toast.error(
            err instanceof ApiError ? err.detail : "Düzeltme kaydedilemedi.",
          );
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
          <DialogDescription>
            Düzeltmeniz bu yorumu anında günceller ve sistem benzer
            yorumlarda bu kararı örnek alır — modeli siz eğitirsiniz.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>Duygu</Label>
            <Select
              value={sentiment}
              onValueChange={(v) => v && setSentiment(v as SentimentValue)}
            >
              <SelectTrigger>
                <SelectValue />
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
            <Label>Kategori</Label>
            <Select value={category} onValueChange={(v) => v && setCategory(v)}>
              <SelectTrigger>
                <SelectValue />
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
                {!(categories.data ?? []).some(
                  (c) => c.code === currentCategory,
                ) && (
                  <SelectItem value={currentCategory}>
                    {currentCategory}
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
              Gerekçe, yapay zekaya örnek olarak verilir ve benzer
              durumlarda kararı yönlendirir.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            type="button"
            onClick={() => setOpen(false)}
          >
            Vazgeç
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={unchanged || correct.isPending}
            title={unchanged ? "Karardan farklı bir değer seçin" : undefined}
          >
            {correct.isPending ? "Kaydediliyor…" : "Düzeltmeyi Kaydet"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
