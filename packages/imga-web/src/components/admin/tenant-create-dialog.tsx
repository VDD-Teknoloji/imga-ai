"use client";

import { CheckCircle2, Copy, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { TerminologyEditor } from "@/components/onboarding/terminology-editor";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useCreateAdminTenant } from "@/hooks/use-admin-tenants";
import {
  sanitizeTerminology,
  type AdminTenantCreateRequestWithProfile,
  type TerminologyEntry,
} from "@/hooks/use-onboarding";
import { ApiError } from "@/lib/api-client";
import { LOCALES, LOCALE_LABELS, type Locale } from "@/lib/i18n/config";
import { useTranslation } from "@/lib/i18n/use-translation";
import { autoSlug, isValidSlug } from "@/lib/slug";
import {
  COMPANY_SIZE_OPTIONS,
  INDUSTRY_OPTIONS,
  type AutomationMode,
  type TenantPlanTier,
} from "@/lib/types";
import { AUTOMATION_MODE_LABELS, PLAN_TIER_LABELS } from "@/lib/user-helpers";

interface TenantCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const PLAN_OPTIONS: ReadonlyArray<TenantPlanTier> = ["trial", "starter", "business", "enterprise"];

const AUTOMATION_OPTIONS: ReadonlyArray<AutomationMode> = ["manual", "semi_auto", "full_auto"];

const INDUSTRY_OTHER_MAX = 128;
const DESCRIPTION_MAX = 500;

type WizardStep = 1 | 2;

/**
 * Three-step wizard: (1) basic fields, (2) optional profile (industry /
 * size / description / terminology — feeds SWOT/OKR/brifing prompts,
 * skippable), (3) invite-link success view. Tenant creation itself
 * fires at the end of step 2 (either "İleri" with profile fields, or
 * "Atla" without) — step 3 only renders when the create response
 * carries an invitation token (mirrors the pre-wizard behavior: no
 * ``initial_admin`` means no token, and the dialog just closes).
 *
 * AI category suggestion is deliberately NOT a wizard step — a brand
 * new tenant has no reviews/keywords yet for suggest-categories to
 * work from. The success view points at /settings/taxonomies instead.
 */
export function TenantCreateDialog({ open, onOpenChange }: TenantCreateDialogProps) {
  const [step, setStep] = useState<WizardStep>(1);

  // --- step 1: basics ---
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [planTier, setPlanTier] = useState<TenantPlanTier>("trial");
  const [automationMode, setAutomationMode] = useState<AutomationMode>("semi_auto");
  const [language, setLanguage] = useState<Locale>("tr");
  const [seedAdmin, setSeedAdmin] = useState(false);
  const [adminEmail, setAdminEmail] = useState("");
  const [adminFullName, setAdminFullName] = useState("");

  // --- step 2: profile (all optional, entire step skippable) ---
  const [industry, setIndustry] = useState("");
  const [industryOtherText, setIndustryOtherText] = useState("");
  const [companySize, setCompanySize] = useState("");
  const [description, setDescription] = useState("");
  const [terminology, setTerminology] = useState<TerminologyEntry[]>([]);

  const [successToken, setSuccessToken] = useState<string | null>(null);
  const [createdTenantName, setCreatedTenantName] = useState<string | null>(null);

  const { t } = useTranslation();
  const create = useCreateAdminTenant();

  // Render-time conditional setState (Sprint 7.6.5 React 19 pattern):
  // reset everything when the dialog closes, including the success
  // state and wizard position that may have been left from a prior
  // open.
  const [lastOpen, setLastOpen] = useState(open);
  if (lastOpen !== open) {
    setLastOpen(open);
    if (!open) {
      setStep(1);
      setName("");
      setSlug("");
      setSlugTouched(false);
      setPlanTier("trial");
      setAutomationMode("semi_auto");
      setLanguage("tr");
      setSeedAdmin(false);
      setAdminEmail("");
      setAdminFullName("");
      setIndustry("");
      setIndustryOtherText("");
      setCompanySize("");
      setDescription("");
      setTerminology([]);
      setSuccessToken(null);
      setCreatedTenantName(null);
    }
  }

  // Auto-derive slug from name as long as the user hasn't manually
  // edited it. Once they type in the slug field, we stop overwriting.
  const effectiveSlug = slugTouched ? slug : autoSlug(name);

  const slugIsValid = effectiveSlug.length > 0 && isValidSlug(effectiveSlug);
  const step1Valid =
    name.trim().length > 0 &&
    slugIsValid &&
    (!seedAdmin || (adminEmail.trim().length > 0 && adminFullName.trim().length > 0));

  const otherRequired = industry === "other";
  const otherMissing = otherRequired && industryOtherText.trim().length === 0;
  const otherTooLong = industryOtherText.length > INDUSTRY_OTHER_MAX;
  const descriptionTooLong = description.length > DESCRIPTION_MAX;
  const step2Valid = !otherMissing && !otherTooLong && !descriptionTooLong;

  async function createTenant(includeProfile: boolean) {
    if (!step1Valid || create.isPending) return;
    if (includeProfile && !step2Valid) return;
    const body: AdminTenantCreateRequestWithProfile = {
      name: name.trim(),
      slug: effectiveSlug,
      plan_tier: planTier,
      automation_mode: automationMode,
      language,
      initial_admin: seedAdmin
        ? {
            email: adminEmail.trim(),
            full_name: adminFullName.trim(),
          }
        : undefined,
    };
    if (includeProfile) {
      body.industry = industry || null;
      body.industry_other_text = industry === "other" ? industryOtherText.trim() : null;
      body.company_size = companySize || null;
      body.business_description = description.trim() || null;
      body.terminology = sanitizeTerminology(terminology);
    }
    try {
      const result = await create.mutateAsync(body);
      setCreatedTenantName(result.tenant.name);
      if (result.initial_invitation_token) {
        setSuccessToken(result.initial_invitation_token);
        toast.success(t("admin.tenantCreate.toast.createdTitle"), {
          description: t("admin.tenantCreate.toast.createdInvite"),
        });
      } else {
        toast.success(t("admin.tenantCreate.toast.createdTitle"));
        onOpenChange(false);
      }
    } catch (err) {
      // Slug conflicts surface on step 2 (create fires there) but the
      // field lives on step 1 — jump back so the fix is one click away.
      if (err instanceof ApiError && err.status === 409) {
        setStep(1);
      }
      toast.error(t("admin.tenantCreate.toast.createError"), {
        description: t(describeError(err)),
      });
    }
  }

  function handleFormSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (step === 1) {
      if (!step1Valid) return;
      setStep(2);
      return;
    }
    void createTenant(true);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-md">
        {successToken && createdTenantName ? (
          <SuccessView
            tenantName={createdTenantName}
            token={successToken}
            onClose={() => onOpenChange(false)}
          />
        ) : (
          <form onSubmit={handleFormSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("admin.tenantCreate.title")}</DialogTitle>
              <DialogDescription>
                {step === 1
                  ? t("admin.tenantCreate.desc")
                  : t("admin.tenantCreate.step.profileDesc")}
              </DialogDescription>
            </DialogHeader>

            <StepIndicator current={step} />

            {step === 1 ? (
              <StepOneFields
                name={name}
                setName={setName}
                effectiveSlug={effectiveSlug}
                slugIsValid={slugIsValid}
                onSlugChange={(v) => {
                  setSlugTouched(true);
                  setSlug(v);
                }}
                planTier={planTier}
                setPlanTier={setPlanTier}
                automationMode={automationMode}
                setAutomationMode={setAutomationMode}
                language={language}
                setLanguage={setLanguage}
                seedAdmin={seedAdmin}
                setSeedAdmin={setSeedAdmin}
                adminEmail={adminEmail}
                setAdminEmail={setAdminEmail}
                adminFullName={adminFullName}
                setAdminFullName={setAdminFullName}
              />
            ) : (
              <StepTwoFields
                industry={industry}
                setIndustry={setIndustry}
                industryOtherText={industryOtherText}
                setIndustryOtherText={setIndustryOtherText}
                otherRequired={otherRequired}
                otherMissing={otherMissing}
                otherTooLong={otherTooLong}
                companySize={companySize}
                setCompanySize={setCompanySize}
                description={description}
                setDescription={setDescription}
                descriptionTooLong={descriptionTooLong}
                terminology={terminology}
                setTerminology={setTerminology}
              />
            )}

            <DialogFooter>
              {step === 1 ? (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => onOpenChange(false)}
                    disabled={create.isPending}
                  >
                    {t("admin.action.cancel")}
                  </Button>
                  <Button type="submit" disabled={!step1Valid} className="gap-2">
                    {t("admin.tenantCreate.step.next")}
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setStep(1)}
                    disabled={create.isPending}
                  >
                    {t("admin.tenantCreate.step.back")}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => void createTenant(false)}
                    disabled={create.isPending}
                  >
                    {t("admin.tenantCreate.step.skip")}
                  </Button>
                  <Button
                    type="submit"
                    disabled={!step2Valid || create.isPending}
                    className="gap-2"
                  >
                    {create.isPending
                      ? t("admin.tenantCreate.creating")
                      : t("admin.tenantCreate.create")}
                    <Plus className="size-4" aria-hidden />
                  </Button>
                </>
              )}
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

// --- step indicator -------------------------------------------------------

function StepIndicator({ current }: { current: 1 | 2 | 3 }) {
  const { t } = useTranslation();
  const labels = [
    t("admin.tenantCreate.step.basicsShort"),
    t("admin.tenantCreate.step.profileShort"),
    t("admin.tenantCreate.step.inviteShort"),
  ];
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      {labels.map((label, i) => {
        const n = (i + 1) as 1 | 2 | 3;
        const active = n === current;
        const done = n < current;
        return (
          <li key={label} className="flex items-center gap-1.5">
            <span
              className={
                "flex size-5 items-center justify-center rounded-full border text-[0.7rem] " +
                (active
                  ? "border-primary bg-primary text-primary-foreground"
                  : done
                    ? "border-primary text-primary"
                    : "border-border text-muted-foreground")
              }
            >
              {n}
            </span>
            <span className={active ? "text-foreground font-medium" : "text-muted-foreground"}>
              {label}
            </span>
            {n < 3 && <span className="text-border mx-0.5">—</span>}
          </li>
        );
      })}
    </ol>
  );
}

// --- step 1: basics --------------------------------------------------------

interface StepOneFieldsProps {
  name: string;
  setName: (v: string) => void;
  effectiveSlug: string;
  slugIsValid: boolean;
  onSlugChange: (v: string) => void;
  planTier: TenantPlanTier;
  setPlanTier: (v: TenantPlanTier) => void;
  automationMode: AutomationMode;
  setAutomationMode: (v: AutomationMode) => void;
  language: Locale;
  setLanguage: (v: Locale) => void;
  seedAdmin: boolean;
  setSeedAdmin: (v: boolean) => void;
  adminEmail: string;
  setAdminEmail: (v: string) => void;
  adminFullName: string;
  setAdminFullName: (v: string) => void;
}

function StepOneFields({
  name,
  setName,
  effectiveSlug,
  slugIsValid,
  onSlugChange,
  planTier,
  setPlanTier,
  automationMode,
  setAutomationMode,
  language,
  setLanguage,
  seedAdmin,
  setSeedAdmin,
  adminEmail,
  setAdminEmail,
  adminFullName,
  setAdminFullName,
}: StepOneFieldsProps) {
  const { t } = useTranslation();
  return (
    <>
      <div className="space-y-2">
        <Label htmlFor="tenant-name">{t("admin.field.name")}</Label>
        <Input
          id="tenant-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Acme Inc."
          maxLength={255}
          required
          autoFocus
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="tenant-slug">{t("admin.field.slug")}</Label>
        <Input
          id="tenant-slug"
          value={effectiveSlug}
          onChange={(e) => onSlugChange(e.target.value)}
          placeholder="acme-inc"
          maxLength={64}
          aria-invalid={effectiveSlug.length > 0 && !slugIsValid ? "true" : undefined}
        />
        <p className="text-muted-foreground text-xs">{t("admin.tenantCreate.slugHelp")}</p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="plan-tier">{t("admin.field.plan")}</Label>
          <Select value={planTier} onValueChange={(v) => setPlanTier(v as TenantPlanTier)}>
            <SelectTrigger id="plan-tier">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PLAN_OPTIONS.map((p) => (
                <SelectItem key={p} value={p}>
                  {PLAN_TIER_LABELS[p] ?? p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="automation-mode">{t("admin.field.automation")}</Label>
          <Select
            value={automationMode}
            onValueChange={(v) => setAutomationMode(v as AutomationMode)}
          >
            <SelectTrigger id="automation-mode">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {AUTOMATION_OPTIONS.map((m) => (
                <SelectItem key={m} value={m}>
                  {AUTOMATION_MODE_LABELS[m]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="tenant-language">{t("tenant.language.label")}</Label>
        <Select value={language} onValueChange={(v) => setLanguage(v as Locale)}>
          <SelectTrigger id="tenant-language">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {LOCALES.map((l) => (
              <SelectItem key={l} value={l}>
                {LOCALE_LABELS[l]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("tenant.language.help")}</p>
      </div>

      <div className="space-y-3 rounded-md border p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="space-y-0.5">
            <Label htmlFor="seed-admin">{t("admin.tenantCreate.seedAdminLabel")}</Label>
            <p className="text-muted-foreground text-xs">
              {t("admin.tenantCreate.seedAdminHelp")}
            </p>
          </div>
          <Switch id="seed-admin" checked={seedAdmin} onCheckedChange={setSeedAdmin} />
        </div>
        {seedAdmin ? (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="admin-email">{t("admin.field.email")}</Label>
              <Input
                id="admin-email"
                type="email"
                value={adminEmail}
                onChange={(e) => setAdminEmail(e.target.value)}
                placeholder="alice@acme.com"
                required={seedAdmin}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="admin-name">{t("admin.tenantCreate.fullName")}</Label>
              <Input
                id="admin-name"
                value={adminFullName}
                onChange={(e) => setAdminFullName(e.target.value)}
                placeholder="Alice Smith"
                maxLength={255}
                required={seedAdmin}
              />
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}

// --- step 2: profile (optional) --------------------------------------------

interface StepTwoFieldsProps {
  industry: string;
  setIndustry: (v: string) => void;
  industryOtherText: string;
  setIndustryOtherText: (v: string) => void;
  otherRequired: boolean;
  otherMissing: boolean;
  otherTooLong: boolean;
  companySize: string;
  setCompanySize: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  descriptionTooLong: boolean;
  terminology: TerminologyEntry[];
  setTerminology: (v: TerminologyEntry[]) => void;
}

function StepTwoFields({
  industry,
  setIndustry,
  industryOtherText,
  setIndustryOtherText,
  otherRequired,
  otherMissing,
  otherTooLong,
  companySize,
  setCompanySize,
  description,
  setDescription,
  descriptionTooLong,
  terminology,
  setTerminology,
}: StepTwoFieldsProps) {
  const { t } = useTranslation();
  return (
    <>
      <p className="text-muted-foreground text-xs">{t("admin.tenantCreate.step.profileHelp")}</p>

      <div className="space-y-2">
        <Label htmlFor="create-industry">{t("settings.profile.industry")}</Label>
        <Select value={industry || undefined} onValueChange={(v) => setIndustry(v ?? "")}>
          <SelectTrigger id="create-industry">
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
          <Label htmlFor="create-industry-other">{t("settings.profile.industryOther")}</Label>
          <Input
            id="create-industry-other"
            value={industryOtherText}
            onChange={(e) => setIndustryOtherText(e.target.value)}
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
            {industryOtherText.length} / {INDUSTRY_OTHER_MAX}
            {otherMissing ? t("settings.profile.requiredSuffix") : ""}
          </p>
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="create-company-size">{t("settings.profile.companySize")}</Label>
        <Select value={companySize || undefined} onValueChange={(v) => setCompanySize(v ?? "")}>
          <SelectTrigger id="create-company-size">
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
        <Label htmlFor="create-description">{t("settings.profile.businessDescription")}</Label>
        <Textarea
          id="create-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={DESCRIPTION_MAX}
          rows={3}
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

      <TerminologyEditor value={terminology} onChange={setTerminology} />
    </>
  );
}

// --- success view (token reveal) -----------------------------------------

function SuccessView({
  tenantName,
  token,
  onClose,
}: {
  tenantName: string;
  token: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <CheckCircle2 className="size-5 text-emerald-600" aria-hidden />
          {t("admin.tenantCreate.success.title", { name: tenantName })}
        </DialogTitle>
        <DialogDescription>
          {t("admin.tenantCreate.success.desc1")}
          <strong>{t("admin.invite.onlyOnce")}</strong>
          {t("admin.tenantCreate.success.desc2")}
        </DialogDescription>
      </DialogHeader>

      <StepIndicator current={3} />

      <InviteLinkBlock token={token} />

      <p className="text-muted-foreground bg-muted/40 rounded-lg p-3 text-xs leading-relaxed">
        {t("admin.tenantCreate.success.aiSuggestNote")}
      </p>

      <DialogFooter>
        <Button onClick={onClose}>{t("admin.tenantCreate.success.done")}</Button>
      </DialogFooter>
    </div>
  );
}

interface InviteLinkBlockProps {
  token: string;
}

export function InviteLinkBlock({ token }: InviteLinkBlockProps) {
  const { t } = useTranslation();
  const url = inviteUrl(token);
  return (
    <div className="space-y-2">
      <Label className="text-xs">{t("admin.invite.linkLabel")}</Label>
      <div className="bg-muted/40 flex items-stretch gap-2 rounded-md border p-1">
        <code className="flex-1 self-center truncate px-2 font-mono text-xs">{url}</code>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              toast.success(t("admin.invite.copied"));
            } catch {
              toast.error(t("admin.invite.copyFailed"));
            }
          }}
        >
          <Copy className="size-3.5" aria-hidden />
          {t("admin.invite.copy")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("admin.invite.linkHelp")}</p>
    </div>
  );
}

function inviteUrl(token: string): string {
  // Browser-only: window.location.origin gives the current host so
  // staging / production / local all build the right link without
  // hardcoded URLs.
  if (typeof window !== "undefined") {
    return `${window.location.origin}/invite/${token}`;
  }
  return `/invite/${token}`;
}

/** i18n anahtarı döndürür; çağıran `t(...)` ile çevirir (describeError
 *  modül seviyesinde, hook erişimi yok). */
function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "admin.tenantCreate.error.slugTaken";
    if (err.status === 403) return "admin.error.superAdminRequired";
    if (err.status === 422) return "admin.error.invalidForm";
  }
  return "admin.error.unexpected";
}
