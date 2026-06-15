"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  useCreateCustomCategory,
  useUpdateCustomCategory,
} from "@/hooks/use-tenant-config";
import type { CategoryView } from "@/lib/types";
import { cn } from "@/lib/utils";

interface CustomCategoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edit mode if set; create mode otherwise. */
  category?: CategoryView;
}

/** Validation: lowercase letters digits underscore, must start with a letter. */
const CODE_REGEX = /^[a-z][a-z0-9_]*$/;

interface FormState {
  code: string;
  label_tr: string;
  label_en: string;
  description: string;
}

const EMPTY_FORM: FormState = {
  code: "",
  label_tr: "",
  label_en: "",
  description: "",
};

function formFromCategory(cat: CategoryView): FormState {
  return {
    code: cat.code,
    label_tr: cat.label_tr,
    label_en: cat.label_en ?? "",
    description: cat.description ?? "",
  };
}

export function CustomCategoryDialog({
  open,
  onOpenChange,
  category,
}: CustomCategoryDialogProps) {
  const create = useCreateCustomCategory();
  const update = useUpdateCustomCategory();
  const isEdit = category !== undefined;
  const isPending = create.isPending || update.isPending;

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [touched, setTouched] = useState({ code: false, label_tr: false });

  // Re-seed the form whenever the dialog opens — for create, blank;
  // for edit, the row's current values. Tracked via the
  // (open, category.id) tuple using the React 19 prop-tracking
  // pattern; this avoids the cascading re-render warning that
  // useEffect + setState triggers under react-hooks/set-state-in-effect.
  const seedKey = open ? (category?.id ?? "__new__") : "__closed__";
  const [lastSeedKey, setLastSeedKey] = useState(seedKey);
  if (lastSeedKey !== seedKey) {
    setLastSeedKey(seedKey);
    if (open) {
      setForm(category ? formFromCategory(category) : EMPTY_FORM);
      setTouched({ code: false, label_tr: false });
    }
  }

  const codeError = (() => {
    if (form.code.trim() === "") return "Kod gerekli.";
    if (!CODE_REGEX.test(form.code))
      return "Sadece küçük harf, rakam, alt çizgi; harf ile başlamalı.";
    return null;
  })();
  const labelError = form.label_tr.trim() === "" ? "Etiket gerekli." : null;

  const canSubmit = !isPending && codeError === null && labelError === null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ code: true, label_tr: true });
    if (!canSubmit) return;

    const payload = {
      label_tr: form.label_tr.trim(),
      label_en: form.label_en.trim() || null,
      description: form.description.trim() || null,
    };

    if (isEdit && category) {
      update.mutate(
        { categoryId: category.id, ...payload },
        { onSuccess: () => onOpenChange(false) },
      );
    } else {
      create.mutate(
        { code: form.code.trim(), ...payload, label_en: payload.label_en ?? undefined, description: payload.description ?? undefined },
        { onSuccess: () => onOpenChange(false) },
      );
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>
              {isEdit ? "Özel kategoriyi düzenle" : "Yeni özel kategori"}
            </DialogTitle>
            <DialogDescription>
              {isEdit
                ? "Etiketleri ve açıklamayı güncelleyebilirsin. Kod sabit kalır."
                : "Kuruma özel kategori ekle. Kod sonradan değiştirilemez."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="cat-code">Kod</Label>
              <Input
                id="cat-code"
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                onBlur={() => setTouched((t) => ({ ...t, code: true }))}
                placeholder="ornek_kategori"
                disabled={isEdit || isPending}
                autoComplete="off"
                spellCheck={false}
                className={cn(
                  "font-mono text-sm",
                  touched.code && codeError && "border-destructive",
                )}
              />
              {touched.code && codeError ? (
                <p className="text-destructive text-xs">{codeError}</p>
              ) : (
                <p className="text-muted-foreground text-xs">
                  Sadece küçük harf, rakam, alt çizgi. Global kategori kodlarıyla
                  çakışamaz.
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="cat-label-tr">
                Etiket (TR) <span className="text-destructive">*</span>
              </Label>
              <Input
                id="cat-label-tr"
                value={form.label_tr}
                onChange={(e) => setForm({ ...form, label_tr: e.target.value })}
                onBlur={() => setTouched((t) => ({ ...t, label_tr: true }))}
                placeholder="VIP Müşteri Şikayeti"
                disabled={isPending}
                className={cn(touched.label_tr && labelError && "border-destructive")}
              />
              {touched.label_tr && labelError ? (
                <p className="text-destructive text-xs">{labelError}</p>
              ) : null}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="cat-label-en">Etiket (EN, opsiyonel)</Label>
              <Input
                id="cat-label-en"
                value={form.label_en}
                onChange={(e) => setForm({ ...form, label_en: e.target.value })}
                placeholder="VIP Customer Complaint"
                disabled={isPending}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="cat-description">Açıklama (opsiyonel)</Label>
              <Textarea
                id="cat-description"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="Hangi durumda bu kategoriyi seçmeli?"
                rows={3}
                disabled={isPending}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isPending}
            >
              Vazgeç
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {isPending ? "Kaydediliyor..." : isEdit ? "Kaydet" : "Oluştur"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
