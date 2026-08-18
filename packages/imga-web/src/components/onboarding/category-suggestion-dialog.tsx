"use client";

// WS1 — /settings/taxonomies "Yapay Zekâ ile Öner" akışı.
//
// suggest-categories PERSIST ETMEZ (yalnız döner); kullanıcı üç
// bölümden (yeni ana kategoriler / alt kategoriler / kapatılması
// önerilen globaller) istediği alt kümeyi işaretler, apply-categories
// tek transaction'da yazar. 412 (LLM anahtarı yok) proaktif olarak
// useLlmCredentials ile kapılanır — root-cause-dialog.tsx'teki
// NoCredentialBanner deseniyle aynı; sunucu yine de 412/503 dönerse
// aynı sabit Türkçe mesajlar toast olarak gösterilir (apiRequest
// `detail` alanı string olmayan gövdeleri "HTTP nnn"e düşürdüğü için
// bu iki durumda gövdeyi ayrıştırmaya çalışmak yerine sabit metin
// tercih edilir — bkz. use-onboarding.apiErrorMessage yorumu).
//
// apply-categories tek transaction: ilk çakışma tüm isteği düşürür.
// Satır-düzeyi hata gösterimi bu yüzden bir liste değil TEK bir
// {code, message} — hata mesajındaki (Python !r ile gömülü) kodu
// extractCodeFromMessage ile ayrıştırıp ilgili satırın altına basar;
// kod çıkaramazsa genel bir banner'a düşer.

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCategories } from "@/hooks/use-categories";
import { useLlmCredentials } from "@/hooks/use-llm-credentials";
import {
  apiErrorMessage,
  extractCodeFromMessage,
  useApplyCategories,
  useSuggestCategories,
  type ApplyCategoriesRequest,
  type SuggestCategoriesResponse,
} from "@/hooks/use-onboarding";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

interface CategorySuggestionDialogProps {
  open: boolean;
  onClose: () => void;
}

export function CategorySuggestionDialog({ open, onClose }: CategorySuggestionDialogProps) {
  const { t } = useTranslation();
  const router = useRouter();

  const credentials = useLlmCredentials();
  const hasActiveKey = (credentials.data ?? []).some((c) => c.is_active);
  const credentialsLoaded = !credentials.isLoading;

  const categories = useCategories();
  const globalLabelByCode = new Map(
    (categories.data ?? []).filter((c) => c.is_global).map((c) => [c.code, c.label_tr]),
  );

  const suggest = useSuggestCategories();
  const apply = useApplyCategories();

  const [suggestion, setSuggestion] = useState<SuggestCategoriesResponse | null>(null);
  const [selectedTop, setSelectedTop] = useState<Set<string>>(new Set());
  const [selectedSub, setSelectedSub] = useState<Set<string>>(new Set());
  const [selectedDisable, setSelectedDisable] = useState<Set<string>>(new Set());
  const [rowError, setRowError] = useState<{ code: string; message: string } | null>(null);
  const [bannerError, setBannerError] = useState<string | null>(null);

  // Reset on open — same form-mirror pattern as CreateModal/EditModal
  // in this page's parent (/settings/taxonomies).
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (open) {
      setSuggestion(null);
      setSelectedTop(new Set());
      setSelectedSub(new Set());
      setSelectedDisable(new Set());
      setRowError(null);
      setBannerError(null);
    }
  }, [open]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function toggle(
    setter: React.Dispatch<React.SetStateAction<Set<string>>>,
    code: string,
    checked: boolean,
  ) {
    setter((prev) => {
      const next = new Set(prev);
      if (checked) next.add(code);
      else next.delete(code);
      return next;
    });
  }

  function onSuggest() {
    setBannerError(null);
    suggest.mutate(
      {},
      {
        onSuccess: (data) => {
          setSuggestion(data);
          setSelectedTop(new Set(data.top_categories.map((c) => c.code)));
          setSelectedSub(new Set(data.subcategories.map((s) => s.code)));
          setSelectedDisable(new Set(data.disable_global_codes));
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 412) {
            toast.error(t("settings.taxonomies.aiSuggest.noCredentials"));
            return;
          }
          if (err instanceof ApiError && err.status === 503) {
            toast.error(t("settings.taxonomies.aiSuggest.providerUnavailable"));
            return;
          }
          toast.error(apiErrorMessage(err, t("settings.taxonomies.aiSuggest.suggestFailed")));
        },
      },
    );
  }

  function onApply() {
    if (!suggestion) return;
    setRowError(null);
    setBannerError(null);

    // A subcategory may point at a suggested (not-yet-existing) top
    // category as its parent. If the user unchecked that parent but
    // left the subcategory checked, apply-categories 400s (the parent
    // never gets created, so it's outside the backend's allowed-primary
    // set) — catch it client-side so the error lands on the row the
    // user actually needs to fix, not a misattributed banner.
    const suggestedTopCodes = new Set(suggestion.top_categories.map((c) => c.code));
    const orphan = suggestion.subcategories.find(
      (s) =>
        selectedSub.has(s.code) &&
        suggestedTopCodes.has(s.primary_category_code) &&
        !selectedTop.has(s.primary_category_code),
    );
    if (orphan) {
      setRowError({
        code: orphan.code,
        message: t("settings.taxonomies.aiSuggest.parentRequired", {
          parent: orphan.primary_category_code,
        }),
      });
      return;
    }

    const body: ApplyCategoriesRequest = {
      top_categories: suggestion.top_categories
        .filter((c) => selectedTop.has(c.code))
        .map((c) => ({ code: c.code, label_tr: c.label_tr, description: c.description || null })),
      subcategories: suggestion.subcategories
        .filter((s) => selectedSub.has(s.code))
        .map((s) => ({
          code: s.code,
          label_tr: s.label_tr,
          primary_category_code: s.primary_category_code,
        })),
      disable_global_codes: suggestion.disable_global_codes.filter((c) => selectedDisable.has(c)),
    };
    apply.mutate(body, {
      onSuccess: (result) => {
        const total =
          result.created_categories.length +
          result.created_taxonomies.length +
          result.disabled_global_codes.length;
        toast.success(t("settings.taxonomies.aiSuggest.applied", { n: total }));
        onClose();
      },
      onError: (err) => {
        const message = apiErrorMessage(err, t("settings.taxonomies.aiSuggest.applyFailed"));
        if (err instanceof ApiError && (err.status === 400 || err.status === 409)) {
          const code = extractCodeFromMessage(message);
          if (code) {
            setRowError({ code, message });
            return;
          }
        }
        setBannerError(message);
      },
    });
  }

  const selectionCount = selectedTop.size + selectedSub.size + selectedDisable.size;
  const canApply = suggestion !== null && selectionCount > 0 && !apply.isPending;
  const hasAnySuggestion =
    suggestion !== null &&
    (suggestion.top_categories.length > 0 ||
      suggestion.subcategories.length > 0 ||
      suggestion.disable_global_codes.length > 0);

  return (
    <Dialog open={open} onOpenChange={(v) => (v ? null : onClose())}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="text-primary size-5" aria-hidden />
            {t("settings.taxonomies.aiSuggest.title")}
          </DialogTitle>
          <DialogDescription>{t("settings.taxonomies.aiSuggest.desc")}</DialogDescription>
        </DialogHeader>

        {credentialsLoaded && !hasActiveKey && (
          <div className="flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center sm:justify-between dark:border-amber-900/50 dark:bg-amber-950/30">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 size-5 text-amber-600" aria-hidden />
              <p className="text-sm text-amber-900 dark:text-amber-100">
                {t("settings.taxonomies.aiSuggest.noCredentials")}
              </p>
            </div>
            <Button
              onClick={() => router.push("/settings/integrations")}
              variant="outline"
              className="shrink-0 gap-2"
            >
              {t("settings.taxonomies.aiSuggest.addKey")}
              <ArrowRight className="size-4" aria-hidden />
            </Button>
          </div>
        )}

        {bannerError && (
          <div className="border-destructive/30 bg-destructive/5 rounded-lg border p-3 text-sm text-destructive">
            {bannerError}
          </div>
        )}

        {!suggestion && (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <p className="text-muted-foreground text-sm">
              {t("settings.taxonomies.aiSuggest.intro")}
            </p>
            <Button
              onClick={onSuggest}
              disabled={suggest.isPending || !credentialsLoaded || !hasActiveKey}
              className="gap-2"
            >
              {suggest.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Sparkles className="size-4" aria-hidden />
              )}
              {suggest.isPending
                ? t("settings.taxonomies.aiSuggest.loading")
                : t("settings.taxonomies.aiSuggest.suggestButton")}
            </Button>
          </div>
        )}

        {suggestion && !hasAnySuggestion && (
          <p className="text-muted-foreground py-4 text-sm">
            {t("settings.taxonomies.aiSuggest.empty")}
          </p>
        )}

        {suggestion && hasAnySuggestion && (
          <div className="space-y-5">
            {suggestion.rationale && (
              <p className="bg-muted/40 rounded-lg p-3 text-sm leading-relaxed">
                {suggestion.rationale}
              </p>
            )}

            {suggestion.top_categories.length > 0 && (
              <section className="space-y-2">
                <h4 className="text-sm font-medium">
                  {t("settings.taxonomies.aiSuggest.topCategoriesTitle")}
                </h4>
                <ul className="space-y-1.5">
                  {suggestion.top_categories.map((c) => (
                    <li key={c.code} className="rounded-md border p-2">
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={selectedTop.has(c.code)}
                          onChange={(e) => toggle(setSelectedTop, c.code, e.target.checked)}
                          className="mt-0.5 size-4"
                        />
                        <span className="flex-1">
                          <span className="font-medium">{c.label_tr}</span>{" "}
                          <code className="text-muted-foreground text-xs">{c.code}</code>
                          {c.description && (
                            <p className="text-muted-foreground mt-0.5 text-xs">
                              {c.description}
                            </p>
                          )}
                          {rowError?.code === c.code && (
                            <p className="text-destructive mt-1 text-xs">{rowError.message}</p>
                          )}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {suggestion.subcategories.length > 0 && (
              <section className="space-y-2">
                <h4 className="text-sm font-medium">
                  {t("settings.taxonomies.aiSuggest.subcategoriesTitle")}
                </h4>
                <ul className="space-y-1.5">
                  {suggestion.subcategories.map((s) => (
                    <li key={s.code} className="rounded-md border p-2">
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={selectedSub.has(s.code)}
                          onChange={(e) => toggle(setSelectedSub, s.code, e.target.checked)}
                          className="mt-0.5 size-4"
                        />
                        <span className="flex-1">
                          <span className="font-medium">{s.label_tr}</span>{" "}
                          <code className="text-muted-foreground text-xs">{s.code}</code>
                          <p className="text-muted-foreground mt-0.5 text-xs">
                            {t("settings.taxonomies.aiSuggest.subOf", {
                              parent:
                                globalLabelByCode.get(s.primary_category_code) ??
                                suggestion.top_categories.find(
                                  (c) => c.code === s.primary_category_code,
                                )?.label_tr ??
                                s.primary_category_code,
                            })}
                          </p>
                          {rowError?.code === s.code && (
                            <p className="text-destructive mt-1 text-xs">{rowError.message}</p>
                          )}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {suggestion.disable_global_codes.length > 0 && (
              <section className="space-y-2">
                <h4 className="text-sm font-medium">
                  {t("settings.taxonomies.aiSuggest.disableTitle")}
                </h4>
                <ul className="space-y-1.5">
                  {suggestion.disable_global_codes.map((code) => (
                    <li key={code} className="rounded-md border p-2">
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={selectedDisable.has(code)}
                          onChange={(e) => toggle(setSelectedDisable, code, e.target.checked)}
                          className="mt-0.5 size-4"
                        />
                        <span className="flex-1">
                          <span className="font-medium">
                            {globalLabelByCode.get(code) ?? code}
                          </span>{" "}
                          <code className="text-muted-foreground text-xs">{code}</code>
                          {rowError?.code === code && (
                            <p className="text-destructive mt-1 text-xs">{rowError.message}</p>
                          )}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          {suggestion && hasAnySuggestion && (
            <Button onClick={onApply} disabled={!canApply} className="gap-2">
              {apply.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
              {t("settings.taxonomies.aiSuggest.apply", { n: selectionCount })}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
