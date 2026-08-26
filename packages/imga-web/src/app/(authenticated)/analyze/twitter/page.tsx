"use client";

// "Twitter'dan Çek" — X/Twitter'dan arama terimiyle gönderi çekip
// standart batch pipeline'ına veren tek adımlı form. Başarıda kullanıcı
// /analyze/upload'a yönlenir; oradaki useActiveBatchJob kuyruğa alınan
// işi bulup ilerleme ekranına kendiliğinden bağlanır — bu sayfa ilerleme
// tutmaz. Form tek-atımlık taslak state'tir (filtre/sekme değil), URL
// paramı gerektirmez.

import { ChevronLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

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
import { useTwitterImportMutation } from "@/hooks/use-batch-uploads";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

const COUNT_OPTIONS = ["100", "250", "500", "1000"] as const;

export default function TwitterImportPage() {
  return (
    <RequireRole level="write">
      <TwitterImportPageInner />
    </RequireRole>
  );
}

function TwitterImportPageInner() {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  const router = useRouter();
  const importMutation = useTwitterImportMutation();

  const [term, setTerm] = useState("");
  const [count, setCount] = useState<string>("250");
  const [excludeHandle, setExcludeHandle] = useState("");

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
      },
      {
        onSuccess: (res) => {
          const base =
            res.exhausted && res.found < res.requested
              ? t("analyze.twitter.queuedPartial", {
                  found: res.found,
                  requested: res.requested,
                })
              : t("analyze.twitter.queued", { found: res.found });
          const note =
            res.filtered_out > 0
              ? t("analyze.twitter.filteredNote", { n: res.filtered_out })
              : "";
          toast.success(`${base}${note}`);
          router.push("/analyze/upload");
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

  const pending = importMutation.isPending;

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
        <p className="text-muted-foreground text-sm">
          {t("analyze.twitter.subtitle")}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("analyze.twitter.formTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="twitter-term">
                {t("analyze.twitter.termLabel")}
              </Label>
              <Input
                id="twitter-term"
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder={t("analyze.twitter.termPlaceholder")}
                maxLength={200}
                disabled={pending}
                autoFocus
              />
              <p className="text-muted-foreground text-xs">
                {t("analyze.twitter.termHelp")}
              </p>
            </div>

            <div className="grid gap-5 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="twitter-count">
                  {t("analyze.twitter.countLabel")}
                </Label>
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
                <Label htmlFor="twitter-exclude">
                  {t("analyze.twitter.excludeLabel")}
                </Label>
                <div className="relative">
                  <span
                    className="text-muted-foreground pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm"
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
                    disabled={pending}
                    className="pl-8"
                  />
                </div>
                <p className="text-muted-foreground text-xs">
                  {t("analyze.twitter.excludeHelp")}
                </p>
              </div>
            </div>

            <div className="bg-muted/50 text-muted-foreground rounded-lg p-3 text-xs leading-relaxed">
              <span className="text-foreground font-medium">
                {t("analyze.twitter.infoTitle")}
              </span>{" "}
              {t("analyze.twitter.info")}
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-muted-foreground text-xs">
                {t("analyze.twitter.durationHint")}
              </p>
              <Button type="submit" disabled={pending || term.trim().length < 2}>
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
    </main>
  );
}
