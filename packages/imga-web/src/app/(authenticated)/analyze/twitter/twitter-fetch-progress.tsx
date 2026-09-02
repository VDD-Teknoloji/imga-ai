"use client";

// "Twitter'dan Çek" arka plan işinin canlı ilerleme kartı. page.tsx
// job_id URL'e yazıldıktan sonra bunu render eder; veri
// useTwitterFetchJobStatus'un 2 sn'lik poll'undan gelir (page.tsx da
// aynı queryKey'i "done" geçişini yakalamak için ayrıca okur —
// TanStack tek istekte birleştirir, iki kez ağ gitmez).
//
// Bar dili BatchProgressStream.tsx'teki BatchProgressBar ile BİREBİR
// aynı (gradient dolgu + --motion-ease geçişi, indeterminate şerit
// için progress-slide keyframe) — iki ilerleme çubuğu görsel olarak
// tutarlı kalsın diye kasıtlı tekrar (paylaşılan bileşene çıkarmak bu
// görevin kapsamı dışında, dosya sahipliği use-batch-uploads.ts'e
// dokunmayı gerektirir).

import { CircleAlert, Clock, Hourglass, Radar, RotateCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  buildTwitterImportSummary,
  readTwitterFetchJobMemo,
  useTwitterFetchJobStatus,
  type TwitterFetchJobMemo,
  type TwitterFetchJobStatusResponse,
} from "@/hooks/use-twitter-fetch";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const restMinutes = minutes % 60;
    return `${hours}:${String(restMinutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatTweetDate(iso: string, locale: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(locale === "en" ? "en-US" : "tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function buildFailedMessage(
  data: TwitterFetchJobStatusResponse,
  term: string | null,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  switch (data.error) {
    case "no_results":
      return t("analyze.twitter.noResultsError", {
        term: term ?? "—",
        fetched: data.fetched_total,
        filteredOut: data.filtered_out,
      });
    case "no_relevant_results":
      return t("analyze.twitter.noRelevantError", {
        found: data.kept_after_filter ?? data.tweets_found,
      });
    case "fetch_failed":
    case "internal_error":
    default:
      return t("analyze.twitter.failed");
  }
}

function ProgressBar({ percent }: { percent: number }) {
  const pct = Math.max(0, Math.min(100, percent));
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
      <div
        className="from-primary to-brand h-2.5 rounded-full bg-gradient-to-r transition-[width] duration-500 [transition-timing-function:var(--motion-ease)]"
        style={{ width: `${pct}%` }}
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      />
    </div>
  );
}

function IndeterminateBar() {
  return (
    <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
      <div className="from-primary/30 via-primary to-primary/30 absolute inset-y-0 w-1/3 animate-[progress-slide_1.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r" />
    </div>
  );
}

interface Props {
  jobId: string;
  /** İş "done" ile başlarsa (F5/geri-tuşu) otomatik yönlendirme
   *  YAPILMAZ (page.tsx'in geçiş guard'ı) — bu durumda kart, kullanıcı
   *  tıkladığında devam eden bir CTA gösterir. */
  onContinue: () => void;
  onRetry: () => void;
}

export function TwitterFetchProgressCard({ jobId, onContinue, onRetry }: Props) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  const query = useTwitterFetchJobStatus(jobId);
  const is404 = query.error instanceof ApiError && query.error.status === 404;
  const isTerminal = is404 || query.data?.status === "done" || query.data?.status === "failed";

  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState<number | null>(null);
  const [memo, setMemo] = useState<TwitterFetchJobMemo | null>(null);

  useEffect(() => {
    // INTENT: localStorage okuma + Date.now() render'da DEĞİL, burada
    // (react-hooks/purity) — job başına bir kez başlangıç anını/
    // önbelleği sabitle (F5'te localStorage'dan devam).
    const cached = readTwitterFetchJobMemo(jobId);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMemo(cached);
    setStartedAt(cached?.startedAt ?? Date.now());
    setNow(Date.now());
  }, [jobId]);

  useEffect(() => {
    // Ayrı efekt (jobId'ye ek olarak isTerminal'e bağlı) — kart done/
    // failed/lost'a düşünce saniyelik tik durur; "elapsed" zaten yalnız
    // aktif kartta gösteriliyor ama gereksiz re-render'ı boşa sürdürmeye
    // gerek yok.
    if (isTerminal) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [jobId, isTerminal]);

  const elapsedLabel =
    startedAt !== null && now !== null
      ? t("analyze.twitter.progressElapsed", { time: formatElapsed(now - startedAt) })
      : null;

  const data = query.data;

  if (is404) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CircleAlert className="text-muted-foreground size-4" aria-hidden />
            {t("analyze.twitter.progressTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-muted-foreground text-sm">{t("analyze.twitter.jobLost")}</p>
          <div className="flex flex-wrap gap-2">
            <Button render={<Link href="/analyze/upload" />}>{t("analyze.twitter.back")}</Button>
            <Button variant="outline" type="button" onClick={onRetry}>
              <RotateCw className="size-4" aria-hidden />
              {t("common.retry")}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (data?.status === "failed") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CircleAlert className="text-destructive size-4" aria-hidden />
            {t("analyze.twitter.progressTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-red-600 dark:text-red-400">
            {buildFailedMessage(data, memo?.term ?? null, t)}
          </p>
          <Button variant="outline" type="button" onClick={onRetry}>
            <RotateCw className="size-4" aria-hidden />
            {t("common.retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (data?.status === "done") {
    // Canlı geçiş page.tsx'te otomatik toast + yönlendirme yapar; bu
    // dal yalnız "iş zaten bitmişken sayfaya gelindi" (F5/geri) için —
    // aynı özet metni, tıklanınca devam eden bir CTA olarak.
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radar className="size-4" aria-hidden />
            {t("analyze.twitter.progressTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm">
            {buildTwitterImportSummary(data, memo?.relevanceCheckRequested ?? true, t)}
          </p>
          <Button type="button" onClick={onContinue}>
            {t("analyze.twitter.continueToUpload")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const status = data?.status ?? "queued";
  const stage = data?.stage ?? null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2">
            <Radar className="text-primary size-4 animate-pulse" aria-hidden />
            {t("analyze.twitter.progressTitle")}
          </span>
          {elapsedLabel && (
            <span className="text-muted-foreground text-xs font-normal tabular-nums">
              {elapsedLabel}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {status === "queued" && (
          <div className="space-y-2">
            <IndeterminateBar />
            <p className="text-muted-foreground flex items-center gap-1.5 text-sm">
              <Hourglass className="size-3.5" aria-hidden />
              {t("analyze.twitter.progressQueued")}
            </p>
          </div>
        )}

        {status === "running" && stage === "fetching" && data && (
          <div className="space-y-3">
            <ProgressBar
              percent={data.requested > 0 ? (data.tweets_found / data.requested) * 100 : 0}
            />
            <p className="text-muted-foreground text-sm">
              {t("analyze.twitter.progressStageFetching")}
            </p>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
              <span className="text-foreground font-medium tabular-nums">
                {t("analyze.twitter.progressFound", {
                  n: data.tweets_found.toLocaleString(numberLocale),
                })}
              </span>
              <span className="text-muted-foreground tabular-nums">
                {t("analyze.twitter.progressPages", { n: data.pages_done })}
              </span>
              {data.oldest_tweet_at && (
                <span className="text-muted-foreground flex items-center gap-1">
                  <Clock className="size-3.5" aria-hidden />
                  {t("analyze.twitter.progressOldest", {
                    date: formatTweetDate(data.oldest_tweet_at, locale),
                  })}
                </span>
              )}
              {data.excluded_collab > 0 && (
                <Badge variant="secondary">
                  {t("analyze.twitter.progressExcludedCollab", {
                    n: data.excluded_collab,
                  })}
                </Badge>
              )}
            </div>
          </div>
        )}

        {status === "running" && stage === null && (
          // Backend "running"e geçtiği an ile ilk stage'i yazdığı an
          // arasındaki kısa yarış penceresi — çubuk hiçbir karede boş
          // görünmesin diye bekleme metniyle aynı belirsiz şerit.
          <div className="space-y-2">
            <IndeterminateBar />
            <p className="text-muted-foreground text-sm">
              {t("analyze.twitter.progressStageFetching")}
            </p>
          </div>
        )}

        {status === "running" && (stage === "judging" || stage === "finalizing") && data && (
          <div className="space-y-2">
            <IndeterminateBar />
            <p className="text-muted-foreground text-sm">
              {t(
                stage === "judging"
                  ? "analyze.twitter.progressStageJudging"
                  : "analyze.twitter.progressStageFinalizing",
              )}
            </p>
            {stage === "judging" && (
              <p className="text-muted-foreground text-xs">
                {t("analyze.twitter.progressJudging", {
                  n: data.tweets_found.toLocaleString(numberLocale),
                })}
              </p>
            )}
          </div>
        )}

        <p className="text-muted-foreground text-xs">{t("analyze.twitter.progressLeaveHint")}</p>
      </CardContent>
    </Card>
  );
}
