"use client";

// Sprint 8.3.6.6 — /settings/profile.
//
// Tenant context fields (industry / company_size / business_description)
// fed into the SWOT/OKR prompts. Pure form — no URL state needed (the
// persisted state lives in the API response, hooks cache it).
//
// Validation:
//   * industry='other' requires industry_other_text (the backend
//     enforces too; we surface the error inline so the user doesn't
//     burn a round-trip).
//   * industry_other_text max 128 chars (backend column length).
//   * business_description max 500 chars (backend column length).

import { Loader2, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  useTenantProfile,
  useUpdateTenantProfile,
} from "@/hooks/use-tenant-profile";
import { ApiError } from "@/lib/api-client";
import {
  COMPANY_SIZE_OPTIONS,
  INDUSTRY_OPTIONS,
} from "@/lib/types";

const INDUSTRY_OTHER_MAX = 128;
const DESCRIPTION_MAX = 500;

export default function TenantProfilePage() {
  const profile = useTenantProfile();
  const update = useUpdateTenantProfile();

  // Local form mirror so the user can edit freely without each
  // keystroke hitting TanStack Query. Hydrate from the loaded profile;
  // re-hydrate when the server payload changes (after save or fresh
  // fetch).
  const [industry, setIndustry] = useState<string>("");
  const [otherText, setOtherText] = useState<string>("");
  const [size, setSize] = useState<string>("");
  const [description, setDescription] = useState<string>("");

  // Hydrate the local form mirror from the server payload. The four
  // setState calls trip react-hooks/set-state-in-effect, but this is
  // the canonical form-mirror pattern: TanStack Query is the
  // external system, the form fields are React state, and we sync
  // when the query settles or refetches after a save.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!profile.data) return;
    setIndustry(profile.data.industry ?? "");
    setOtherText(profile.data.industry_other_text ?? "");
    setSize(profile.data.company_size ?? "");
    setDescription(profile.data.business_description ?? "");
  }, [profile.data]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const otherRequired = industry === "other";
  const otherMissing = otherRequired && otherText.trim().length === 0;
  const otherTooLong = otherText.length > INDUSTRY_OTHER_MAX;
  const descriptionTooLong = description.length > DESCRIPTION_MAX;
  const canSubmit = useMemo(
    () =>
      !update.isPending &&
      !otherMissing &&
      !otherTooLong &&
      !descriptionTooLong,
    [update.isPending, otherMissing, otherTooLong, descriptionTooLong],
  );

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    update.mutate(
      {
        industry: industry || null,
        industry_other_text: industry === "other" ? otherText.trim() : null,
        company_size: size || null,
        business_description: description.trim() || null,
      },
      {
        onSuccess: () => {
          toast.success("Profil kaydedildi.");
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 422) {
            toast.error("Geçersiz alan: " + err.detail);
            return;
          }
          if (err instanceof ApiError && err.status === 400) {
            toast.error(err.detail);
            return;
          }
          toast.error("Kayıt başarısız.");
        },
      },
    );
  }

  return (
    <main className="mx-auto w-full max-w-2xl space-y-6 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          Şirket Profili
        </h1>
        <p className="text-muted-foreground text-sm">
          Bu bilgiler stratejik raporlarda (SWOT, OKR) prompta verilir;
          sektöre ve büyüklüğe göre özelleştirilmiş analiz üretilir.
        </p>
      </header>

      {profile.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      ) : profile.isError ? (
        <p className="text-destructive p-6 text-sm">
          Profil yüklenemedi.
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="industry">Sektör</Label>
            <Select
              value={industry || undefined}
              onValueChange={(v) => setIndustry(v ?? "")}
            >
              <SelectTrigger id="industry">
                <SelectValue placeholder="Sektör seçin" />
              </SelectTrigger>
              <SelectContent>
                {INDUSTRY_OPTIONS.map((opt) => (
                  <SelectItem key={opt.code} value={opt.code}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {otherRequired && (
            <div className="space-y-2">
              <Label htmlFor="industry_other_text">
                Sektör (serbest metin)
              </Label>
              <Input
                id="industry_other_text"
                value={otherText}
                onChange={(e) => setOtherText(e.target.value)}
                maxLength={INDUSTRY_OTHER_MAX}
                placeholder="Örn. Kuyumculuk"
                aria-invalid={otherMissing || otherTooLong || undefined}
              />
              <p
                className={
                  "text-muted-foreground text-xs tabular-nums" +
                  (otherMissing || otherTooLong ? " text-destructive" : "")
                }
              >
                {otherText.length} / {INDUSTRY_OTHER_MAX}
                {otherMissing ? " — bu alan zorunlu" : ""}
              </p>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="company_size">Şirket büyüklüğü</Label>
            <Select
              value={size || undefined}
              onValueChange={(v) => setSize(v ?? "")}
            >
              <SelectTrigger id="company_size">
                <SelectValue placeholder="Büyüklük seçin" />
              </SelectTrigger>
              <SelectContent>
                {COMPANY_SIZE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.code} value={opt.code}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="business_description">İş tanımı</Label>
            <Textarea
              id="business_description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={DESCRIPTION_MAX}
              rows={4}
              placeholder="Hangi ürün/hizmeti veriyorsunuz, kimi hedefliyorsunuz?"
              aria-invalid={descriptionTooLong || undefined}
            />
            <p
              className={
                "text-muted-foreground text-xs tabular-nums" +
                (descriptionTooLong ? " text-destructive" : "")
              }
            >
              {description.length} / {DESCRIPTION_MAX}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Button type="submit" disabled={!canSubmit} className="gap-2">
              {update.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Save className="size-4" aria-hidden />
              )}
              Kaydet
            </Button>
          </div>
        </form>
      )}
    </main>
  );
}
