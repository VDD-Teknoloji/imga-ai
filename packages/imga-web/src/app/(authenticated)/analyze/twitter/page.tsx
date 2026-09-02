"use client";

// "Twitter'dan Çek" — X/Twitter'dan gönderi çekip standart batch
// pipeline'ına veren form.
//
// 2026-09-02 — çekim arka plana alındı: POST artık 202 {job_id,status}
// döner, gerçek fetch→judge→CSV→enqueue zinciri arq worker'da koşar.
// job_id URL'e yazılır (?job=, url-state-patterns.md — F5/geri-tuşu/
// deep-link'te ilerleme kaybolmasın) ve TwitterFetchProgressCard onu
// 2 sn'de bir poll'lar. İş bitince (canlı geçiş) toast + /analyze/
// upload'a yönlendirme — useActiveBatchJob oradaki normal batch
// ilerlemesine kendiliğinden bağlanır, tıpkı eski akışta olduğu gibi.
// Form tek-atımlık taslak state'tir (filtre/sekme değil); job_id'nin
// aksine URL paramı GEREKTİRMEZ.
//
// 2026-08-26 — iki AI adımı (bkz. api services/twitter_brand_service):
// "AI ile anahtar kelimeleri çıkar" marka + kurum profilinden include/
// exclude terimleri, resmi hesap ve marka özeti üretip TERİM ALANINI
// doldurur (kullanıcı düzenler; plan kalıcı değil). Çekimde "AI alaka
// kontrolü" açıksa gönderiler tek tek "bu marka hakkında mı" diye
// elenir. Sebep: X araması yazar adında da eşleştiği için "karaca"
// Karaca soyadlı herkesin gönderisini getiriyordu.

import { ChevronLeft, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { XLogo } from "@/components/icons/x-logo";
import { RequireRole } from "@/components/auth/require-role";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { useTwitterPlanMutation, type TwitterPlanResult } from "@/hooks/use-batch-uploads";
import {
  buildTwitterImportSummary,
  clearTwitterFetchJobMemo,
  readTwitterFetchJobMemo,
  useTwitterFetchJobStatus,
  useTwitterImportSubmitMutation,
  writeTwitterFetchJobMemo,
  type TwitterFetchJobStatus,
} from "@/hooks/use-twitter-fetch";
import { ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { useTranslation } from "@/lib/i18n/use-translation";

import { TwitterFetchProgressCard } from "./twitter-fetch-progress";

const COUNT_OPTIONS = ["100", "250", "500", "1000"] as const;

export default function TwitterImportPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <RequireRole level="write">
        <TwitterImportPageInner />
      </RequireRole>
    </Suspense>
  );
}

function PageSkeleton() {
  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <div className="bg-muted/50 h-8 w-48 animate-pulse rounded" />
      <div className="bg-muted/50 h-64 w-full animate-pulse rounded-xl" />
    </main>
  );
}

function TwitterImportPageInner() {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const activeContext = useAuthStore((s) => s.activeContext);
  const importMutation = useTwitterImportSubmitMutation();
  const planMutation = useTwitterPlanMutation();

  const [brand, setBrand] = useState(activeContext?.tenant_name ?? "");
  const [term, setTerm] = useState("");
  const [count, setCount] = useState<string>("250");
  const [excludeHandle, setExcludeHandle] = useState("");
  const [relevanceCheck, setRelevanceCheck] = useState(true);
  const [plan, setPlan] = useState<TwitterPlanResult | null>(null);

  // --- job_id URL state (Path B mirror — docs/agent-rules/url-state-patterns.md) ---
  // `|| null` — boş "?job=" (izole edilebilir olsa da) jobId'yi ""
  // yapıp render dalını forma düşürür ama useTwitterFetchJobStatus'un
  // enabled:jobId!==null'ı geçer; boş string'i de "yok" say.
  const [jobId, setJobId] = useState<string | null>(() => searchParams.get("job") || null);
  useEffect(() => {
    const fromUrl = searchParams.get("job") || null;
    // INTENT: URL kaynak-doğru; back/forward/F5/deep-link senkronu.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setJobId((prev) => (prev === fromUrl ? prev : fromUrl));
  }, [searchParams]);

  const jobStatus = useTwitterFetchJobStatus(jobId);

  // Canlı "done" geçişini yalnız BİR KEZ işler (toast + yönlendirme).
  // prevStatusRef null iken status zaten "done" ise (F5/geri-tuşuyla
  // bitmiş bir işe gelindi) OTOMATİK yönlendirmez — TwitterFetchProgressCard
  // bu durumda tıklanabilir bir "devam et" kartı gösterir; aksi halde
  // geri tuşu /analyze/upload'a hemen geri sıçrardı (bounce trap).
  const prevStatusRef = useRef<TwitterFetchJobStatus | null>(null);
  const handledDoneRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!jobId) {
      prevStatusRef.current = null;
      return;
    }
    const data = jobStatus.data;
    const status = data?.status ?? null;
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    if (!data || data.status !== "done") return;
    if (prev === null) return;
    if (handledDoneRef.current.has(jobId)) return;
    handledDoneRef.current.add(jobId);

    // F5 sonrası form relevanceCheck varsayılana (true) döner — job'a
    // bağlı önbellekteki gerçek tercih varsa onu kullan (bkz.
    // twitter-fetch-progress.tsx'in "done" dalıyla aynı desen).
    const relevanceCheckRequested =
      readTwitterFetchJobMemo(jobId)?.relevanceCheckRequested ?? relevanceCheck;
    toast.success(buildTwitterImportSummary(data, relevanceCheckRequested, t));
    clearTwitterFetchJobMemo(jobId);
    void queryClient.invalidateQueries({ queryKey: ["batch-active"] });
    void queryClient.invalidateQueries({ queryKey: ["batch-history"] });
    router.push("/analyze/upload");
    // INTENT: `t` her render'da yeni referans (useTranslation memoize
    // etmiyor) — dep listesine eklemek effect'i her render'da yeniden
    // koşturur; handledDoneRef zaten tek-seferlik uygulamayı garanti
    // ediyor, bu yüzden bilinçli olarak dışarıda bırakıldı.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobStatus.data, relevanceCheck, queryClient, router]);

  function handlePlan() {
    const trimmed = brand.trim();
    if (trimmed.length < 2) {
      toast.error(t("analyze.twitter.planBrandRequired"));
      return;
    }
    planMutation.mutate(
      { brand: trimmed, handle: excludeHandle.trim() || undefined },
      {
        onSuccess: (res) => {
          setPlan(res);
          setTerm(res.term);
          if (res.handle && !excludeHandle.trim()) {
            setExcludeHandle(res.handle);
          }
          toast.success(t("analyze.twitter.planDone"));
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 412) {
            toast.error(t("analyze.twitter.planNoKeys"));
          } else if (err instanceof ApiError) {
            toast.error(err.detail);
          } else {
            toast.error(t("analyze.twitter.planFailed"));
          }
        },
      },
    );
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = term.trim();
    if (trimmed.length < 2) {
      toast.error(t("analyze.twitter.termRequired"));
      return;
    }
    importMutation.mutate(
      {
        term: trimmed,
        count: Number(count),
        excludeHandle: excludeHandle.trim() || undefined,
        brandSummary: plan?.brand_summary || undefined,
        relevanceCheck,
      },
      {
        onSuccess: (res) => {
          // Terim/AI-kontrolü tercihini job'a bağlı önbelleğe yaz —
          // F5 sonrası hata mesajında terimi göstermek ve "elapsed"
          // sayacını kaldığı yerden sürdürmek için (bkz. use-twitter-fetch.ts).
          writeTwitterFetchJobMemo(res.job_id, {
            term: trimmed,
            relevanceCheckRequested: relevanceCheck,
            startedAt: Date.now(),
          });
          const params = new URLSearchParams(searchParams.toString());
          params.set("job", res.job_id);
          setJobId(res.job_id);
          router.push(`${pathname}?${params.toString()}`, { scroll: false });
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 503) {
            toast.error(t("analyze.twitter.notConfigured"));
          } else if (err instanceof ApiError) {
            toast.error(err.detail);
          } else {
            toast.error(t("analyze.twitter.failed"));
          }
        },
      },
    );
  }

  // "Tekrar Dene" (başarısız/kayıp job) — ?job'u temizler, form aynı
  // component instance'ında kaldığı için önceki alan değerleriyle
  // geri döner. replace (push değil) — geri tuşu ölü ?job=... girdisine
  // dönmesin.
  function handleRetry() {
    if (jobId) clearTwitterFetchJobMemo(jobId);
    setJobId(null);
    const params = new URLSearchParams(searchParams.toString());
    params.delete("job");
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  // F5/geri-tuşuyla zaten "done" bulunan job için kart bu CTA'yı
  // gösterir (bkz. yukarıdaki prevStatusRef notu).
  function handleContinue() {
    if (jobId) clearTwitterFetchJobMemo(jobId);
    router.push("/analyze/upload");
  }

  const pending = importMutation.isPending;
  const planning = planMutation.isPending;

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <header className="space-y-2">
        <Link
          href="/analyze/upload"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" /> {t("analyze.twitter.back")}
        </Link>
        <h1 className="flex items-center gap-2.5 text-2xl font-semibold">
          <XLogo className="size-6" aria-hidden />
          {t("analyze.twitter.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("analyze.twitter.subtitle")}</p>
      </header>

      {jobId ? (
        <TwitterFetchProgressCard jobId={jobId} onContinue={handleContinue} onRetry={handleRetry} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("analyze.twitter.formTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-5" noValidate>
              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="twitter-brand">{t("analyze.twitter.brandLabel")}</Label>
                  <Input
                    id="twitter-brand"
                    value={brand}
                    onChange={(e) => setBrand(e.target.value)}
                    placeholder={t("analyze.twitter.brandPlaceholder")}
                    maxLength={120}
                    disabled={pending || planning}
                    autoFocus
                  />
                  <p className="text-muted-foreground text-xs">{t("analyze.twitter.brandHelp")}</p>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="twitter-exclude">{t("analyze.twitter.excludeLabel")}</Label>
                  <div className="relative">
                    <span
                      className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-sm"
                      aria-hidden
                    >
                      @
                    </span>
                    <Input
                      id="twitter-exclude"
                      value={excludeHandle}
                      onChange={(e) => setExcludeHandle(e.target.value)}
                      placeholder={t("analyze.twitter.excludePlaceholder")}
                      maxLength={50}
                      disabled={pending || planning}
                      className="pl-8"
                    />
                  </div>
                  <p className="text-muted-foreground text-xs">
                    {t("analyze.twitter.excludeHelp")}
                  </p>
                </div>
              </div>

              <div>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={handlePlan}
                  disabled={pending || planning || brand.trim().length < 2}
                >
                  {planning ? (
                    <>
                      <Loader2 className="size-4 animate-spin" aria-hidden />
                      {t("analyze.twitter.planning")}
                    </>
                  ) : (
                    <>
                      <Sparkles className="size-4" aria-hidden />
                      {t("analyze.twitter.planButton")}
                    </>
                  )}
                </Button>
              </div>

              {plan && (
                <div className="bg-muted/50 space-y-2 rounded-lg p-3 text-xs leading-relaxed">
                  {plan.brand_summary && (
                    <p>
                      <span className="text-foreground font-medium">
                        {t("analyze.twitter.summaryLabel")}:
                      </span>{" "}
                      <span className="text-muted-foreground">{plan.brand_summary}</span>
                    </p>
                  )}
                  <p>
                    <span className="text-foreground font-medium">
                      {t("analyze.twitter.includeLabel")}:
                    </span>{" "}
                    <span className="text-muted-foreground">{plan.include.join(", ")}</span>
                  </p>
                  {plan.exclude.length > 0 && (
                    <p>
                      <span className="text-foreground font-medium">
                        {t("analyze.twitter.excludeTermsLabel")}:
                      </span>{" "}
                      <span className="text-muted-foreground">{plan.exclude.join(", ")}</span>
                    </p>
                  )}
                  {plan.bare_name_ambiguous && (
                    <p className="text-amber-700 dark:text-amber-400">
                      {t("analyze.twitter.ambiguousNote")}
                    </p>
                  )}
                  {plan.notes && <p className="text-muted-foreground">{plan.notes}</p>}
                </div>
              )}

              <div className="space-y-1.5">
                <Label htmlFor="twitter-term">{t("analyze.twitter.termLabel")}</Label>
                <Textarea
                  id="twitter-term"
                  value={term}
                  onChange={(e) => setTerm(e.target.value)}
                  placeholder={t("analyze.twitter.termPlaceholder")}
                  maxLength={400}
                  rows={3}
                  disabled={pending}
                />
                <p className="text-muted-foreground text-xs">{t("analyze.twitter.termHelp")}</p>
              </div>

              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="twitter-count">{t("analyze.twitter.countLabel")}</Label>
                  <Select value={count} onValueChange={(v) => v && setCount(v)}>
                    <SelectTrigger id="twitter-count" disabled={pending}>
                      {/* Base UI Select.Value çocuk verilmezse ham değeri
                        ("250") basar — kapalı etiketi children-fn ile kur. */}
                      <SelectValue>
                        {(value: string | null) =>
                          t("analyze.twitter.countOption", {
                            n: Number(value ?? count).toLocaleString(numberLocale),
                          })
                        }
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {COUNT_OPTIONS.map((option) => (
                        <SelectItem key={option} value={option}>
                          {t("analyze.twitter.countOption", {
                            n: Number(option).toLocaleString(numberLocale),
                          })}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="twitter-relevance">{t("analyze.twitter.relevanceLabel")}</Label>
                  <div className="flex items-center gap-3 pt-1.5">
                    <Switch
                      id="twitter-relevance"
                      checked={relevanceCheck}
                      onCheckedChange={(checked) => setRelevanceCheck(checked)}
                      disabled={pending}
                    />
                    <p className="text-muted-foreground text-xs">
                      {t("analyze.twitter.relevanceHelp")}
                    </p>
                  </div>
                </div>
              </div>

              <div className="bg-muted/50 text-muted-foreground rounded-lg p-3 text-xs leading-relaxed">
                <span className="text-foreground font-medium">
                  {t("analyze.twitter.infoTitle")}
                </span>{" "}
                {t("analyze.twitter.info")}
              </div>

              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-muted-foreground text-xs">{t("analyze.twitter.durationHint")}</p>
                <Button type="submit" disabled={pending || planning || term.trim().length < 2}>
                  {pending ? (
                    <>
                      <Loader2 className="size-4 animate-spin" aria-hidden />
                      {t("analyze.twitter.submitting")}
                    </>
                  ) : (
                    t("analyze.twitter.submit")
                  )}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </main>
  );
}
