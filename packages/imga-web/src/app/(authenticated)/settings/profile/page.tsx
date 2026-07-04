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

import { RequireRole } from "@/components/auth/require-role";
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
import { useTranslation } from "@/lib/i18n/use-translation";
import {
  COMPANY_SIZE_OPTIONS,
  INDUSTRY_OPTIONS,
} from "@/lib/types";

const INDUSTRY_OTHER_MAX = 128;
const DESCRIPTION_MAX = 500;

export default function TenantProfilePage() {
  return (
    <RequireRole level="admin">
      <TenantProfilePageInner />
    </RequireRole>
  );
}

function TenantProfilePageInner() {
  const profile = useTenantProfile();
  const update = useUpdateTenantProfile();
  const { t } = useTranslation();

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
          toast.success(t("settings.profile.saved"));
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 422) {
            toast.error(t("settings.profile.invalidField", { detail: err.detail }));
            return;
          }
          if (err instanceof ApiError && err.status === 400) {
            toast.error(err.detail);
            return;
          }
          toast.error(t("settings.profile.saveFailed"));
        },
      },
    );
  }

  return (
    <main className="mx-auto w-full max-w-2xl space-y-6 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("settings.profile.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("settings.profile.subtitle")}
        </p>
      </header>

      {profile.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : profile.isError ? (
        <p className="text-destructive p-6 text-sm">
          {t("settings.profile.loadError")}
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="industry">{t("settings.profile.industry")}</Label>
            <Select
              value={industry || undefined}
              onValueChange={(v) => setIndustry(v ?? "")}
            >
              <SelectTrigger id="industry">
                <SelectValue placeholder={t("settings.profile.industryPlaceholder")} />
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
                {t("settings.profile.industryOther")}
              </Label>
              <Input
                id="industry_other_text"
                value={otherText}
                onChange={(e) => setOtherText(e.target.value)}
                maxLength={INDUSTRY_OTHER_MAX}
                placeholder={t("settings.profile.industryOtherPlaceholder")}
                aria-invalid={otherMissing || otherTooLong || undefined}
              />
              <p
                className={
                  "text-muted-foreground text-xs tabular-nums" +
                  (otherMissing || otherTooLong ? " text-destructive" : "")
                }
              >
                {otherText.length} / {INDUSTRY_OTHER_MAX}
                {otherMissing ? t("settings.profile.requiredSuffix") : ""}
              </p>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="company_size">{t("settings.profile.companySize")}</Label>
            <Select
              value={size || undefined}
              onValueChange={(v) => setSize(v ?? "")}
            >
              <SelectTrigger id="company_size">
                <SelectValue placeholder={t("settings.profile.companySizePlaceholder")} />
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
            <Label htmlFor="business_description">
              {t("settings.profile.businessDescription")}
            </Label>
            <Textarea
              id="business_description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={DESCRIPTION_MAX}
              rows={4}
              placeholder={t("settings.profile.businessDescriptionPlaceholder")}
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
              {t("common.save")}
            </Button>
          </div>
        </form>
      )}
    </main>
  );
}
