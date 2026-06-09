"use client";

// Sprint 9.0.5-B A — live batch-progress feed.
//
// Subscribes to /tenants/me/analyze/batch/{jobId}/progress (SSE
// backend shipped in Sprint 9.0.5-A R1) and surfaces the latest
// snapshot to the caller. Replaces the 3s polling on
// ``useBatchJob`` for the upload page so the operator sees progress
// flow in real time during the demo's 5K-run.
//
// Sprint 9.5.5 B — polling fallback. SSE-only was leaving the UI
// "yükleniyor…" forever when a single ``complete`` event got
// dropped (Cloudflare 100s idle kill + backend's 5s terminal-linger
// window combined to lose the terminal frame on a non-trivial
// fraction of batches). The component now arms a 30s quiet-window
// watchdog — if no SSE event arrives in that window, it begins
// polling GET /tenants/me/analyze/batch/{jobId} every 5s, mirrors
// the row state into a snapshot, and fires the same onComplete on
// terminal status. completedRef debounces so a re-arrival of the
// SSE ``complete`` after the poll has already fired doesn't double-
// invoke the caller. onError also kicks the polling immediately.
//
// The component renders nothing by default — it's a state hook +
// optional ``children`` render-prop so the caller can decide the
// presentation. ``BatchProgressBar`` below is the standard
// renderer the upload page uses.

import { useEffect, useRef, useState } from "react";

import { apiRequest } from "@/lib/api-client";
import type { BatchJob } from "@/lib/types";
import { openSseStream, type SseHandle } from "@/lib/sse-client";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

const TERMINAL_STATUSES: ReadonlySet<BatchJob["status"]> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

// Sprint 9.5.5 B — polling fallback timing constants.
// 30s without any SSE frame (progress or ping keepalive) is the
// signal that the stream is dead; the backend emits a ping every
// ~10s when idle so a quiet 30s window is well outside the normal
// jitter envelope.
const SSE_QUIET_TIMEOUT_MS = 30_000;
// Once the polling fallback engages, 5s between DB reads keeps the
// load similar to the pre-SSE Sprint 8.x polling cadence without
// hammering the route.
const POLLING_INTERVAL_MS = 5_000;
// Watchdog fires every 5s; the actual quiet check uses
// SSE_QUIET_TIMEOUT_MS so the resolution is 5s but the trigger is
// the 30s window.
const WATCHDOG_TICK_MS = 5_000;

/** Map a BatchJob row (DB shape) to the same BatchProgressSnapshot
 *  the SSE stream emits. percent is computed since the DB row
 *  doesn't carry it; eta_seconds stays null on the poll path (only
 *  the live stream tracks elapsed wall-clock for an ETA estimate). */
function batchJobToSnapshot(job: BatchJob): BatchProgressSnapshot {
  const percent =
    job.total_rows > 0 ? (job.processed_rows / job.total_rows) * 100 : 0;
  return {
    job_id: job.job_id,
    status: job.status,
    processed: job.processed_rows,
    total: job.total_rows,
    percent,
    succeeded: job.succeeded_rows,
    failed: job.failed_rows,
    tickets_created: job.tickets_created,
    duplicates_skipped: job.duplicates_skipped,
    eta_seconds: null,
    last_checkpoint_row: job.processed_rows,
  };
}

export interface BatchProgressSnapshot {
  job_id: string;
  status: BatchJob["status"];
  processed: number;
  total: number;
  percent: number;
  succeeded: number;
  failed: number;
  tickets_created: number;
  duplicates_skipped: number;
  eta_seconds: number | null;
  last_checkpoint_row: number;
}

export interface BatchProgressStreamProps {
  jobId: string | null;
  /** Optional terminal callback so the caller can refresh
   *  /batches list when the run finishes. */
  onComplete?: (snapshot: BatchProgressSnapshot) => void;
  /** Render prop. ``null`` until the first event lands. */
  children?: (
    snapshot: BatchProgressSnapshot | null,
    error: string | null,
  ) => React.ReactNode;
}

/**
 * Render-prop component. Subscribes to the SSE endpoint when
 * ``jobId`` is set, tears down on unmount or when ``jobId`` flips
 * back to null. Caller controls the actual UI via ``children``.
 */
export function BatchProgressStream({
  jobId,
  onComplete,
  children,
}: BatchProgressStreamProps) {
  const [snapshot, setSnapshot] = useState<BatchProgressSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const handleRef = useRef<SseHandle | null>(null);
  const completedRef = useRef(false);

  // Sprint 9.5.5 B — polling-fallback bookkeeping. Refs (not state)
  // because the watchdog reads + writes them every tick; routing
  // through useState would cause a re-render storm.
  const lastEventAtRef = useRef<number>(Date.now());
  const pollingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const watchdogTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) {
      setSnapshot(null);
      setError(null);
      completedRef.current = false;
      return;
    }
    setError(null);
    completedRef.current = false;
    lastEventAtRef.current = Date.now();
    const url = `${API_BASE}/tenants/me/analyze/batch/${jobId}/progress`;

    // Sprint 9.5.5 B — polling fallback machinery. Defined inside
    // the effect so the closure captures the current jobId; the
    // refs let the watchdog + handlers talk to one shared piece of
    // state without re-creating on every event.
    const fireOnCompleteOnce = (snap: BatchProgressSnapshot) => {
      if (!completedRef.current && TERMINAL_STATUSES.has(snap.status)) {
        completedRef.current = true;
        onComplete?.(snap);
      }
    };

    const stopPolling = () => {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
    };

    const startPolling = () => {
      if (pollingTimerRef.current) return;
      pollingTimerRef.current = setInterval(async () => {
        try {
          const job = await apiRequest<BatchJob>(
            `/tenants/me/analyze/batch/${jobId}`,
          );
          const snap = batchJobToSnapshot(job);
          setSnapshot(snap);
          if (TERMINAL_STATUSES.has(snap.status)) {
            fireOnCompleteOnce(snap);
            stopPolling();
            // Close the (likely stale) SSE handle too — its only
            // purpose was to deliver the complete frame we just
            // recovered from the DB row.
            handleRef.current?.close();
            handleRef.current = null;
          }
        } catch {
          // Swallow — the next watchdog tick will retry. A persistent
          // failure (e.g. 401 cookie expiry) propagates through the
          // api-client's onSessionExpired handler instead.
        }
      }, POLLING_INTERVAL_MS);
    };

    const handle = openSseStream(url, {
      reconnect: true,
      handlers: {
        progress: (payload) => {
          lastEventAtRef.current = Date.now();
          if (payload && typeof payload === "object") {
            setSnapshot(payload as BatchProgressSnapshot);
          }
        },
        complete: (payload) => {
          lastEventAtRef.current = Date.now();
          if (payload && typeof payload === "object") {
            const snap = payload as BatchProgressSnapshot;
            setSnapshot(snap);
            fireOnCompleteOnce(snap);
          }
          stopPolling();
          handleRef.current?.close();
          handleRef.current = null;
        },
        ping: () => {
          // Sprint 9.5.5 B — keepalive resets the watchdog so a
          // healthy idle stream (backend pings ~every 10s) doesn't
          // trip the 30s quiet check.
          lastEventAtRef.current = Date.now();
        },
      },
      onError: (err) => {
        setError(err instanceof Error ? err.message : String(err));
        // Sprint 9.5.5 B — engage the polling fallback immediately
        // on SSE error; don't wait for the 30s quiet timeout. The
        // reconnect machinery in the SSE client will keep trying
        // the stream in parallel, so if it comes back the next
        // event will land + the polling stops on terminal status.
        startPolling();
      },
    });
    handleRef.current = handle;

    // Sprint 9.5.5 B — quiet-window watchdog. Ticks every 5s; engages
    // polling once the gap between now and the last SSE frame
    // exceeds the 30s threshold. Independent of onError because
    // some SSE failures (Cloudflare 100s idle disconnect that the
    // browser silently re-tries) don't surface as errors — the
    // stream just goes quiet.
    watchdogTimerRef.current = setInterval(() => {
      if (completedRef.current) return; // already terminal, nothing to watch
      if (Date.now() - lastEventAtRef.current > SSE_QUIET_TIMEOUT_MS) {
        startPolling();
      }
    }, WATCHDOG_TICK_MS);

    return () => {
      if (watchdogTimerRef.current) {
        clearInterval(watchdogTimerRef.current);
        watchdogTimerRef.current = null;
      }
      stopPolling();
      handle.close();
      handleRef.current = null;
    };
  }, [jobId, onComplete]);

  return <>{children ? children(snapshot, error) : null}</>;
}

/** Sprint 10.0 — yüzdeye göre Türkçe aşama etiketi. Bar henüz
 *  ilerlemiyorken bile kullanıcı "ne oluyor"u okur; işlem hiçbir
 *  anda sessiz görünmez (UML feedback: 100 satırlık dosyada işlem
 *  bitene kadar ekranda bir şey olmuyordu). */
function stageLabel(pct: number, processed: number): string {
  if (processed === 0) return "Yapay zeka yorumlarınızı okumaya başladı…";
  if (pct < 25) return "Duygu analizi yapılıyor…";
  if (pct < 50) return "Kategoriler belirleniyor…";
  if (pct < 75) return "Sonuçlar kaydediliyor…";
  if (pct < 100) return "Son kontroller yapılıyor…";
  return "Tamamlandı";
}

/**
 * Default progress renderer used by /analyze/upload.
 *
 * Sprint 10.0 — yoğun geri bildirim: büyük yüzde, aşama etiketi,
 * canlı başarı/hata sayaçları ve processed===0 iken kayan şerit
 * (indeterminate shimmer) — backend adaptive chunk ile birlikte
 * (worker artık küçük dosyada ~10 kez progress yazar) bar hiçbir
 * aşamada donmuş görünmez.
 */
export function BatchProgressBar({
  jobId,
  onComplete,
}: Pick<BatchProgressStreamProps, "jobId" | "onComplete">) {
  return (
    <BatchProgressStream jobId={jobId} onComplete={onComplete}>
      {(snapshot, error) => {
        if (error) {
          return (
            <div className="text-sm text-red-600">
              Canlı ilerleme bağlantısı koptu: {error}
            </div>
          );
        }
        if (!snapshot) {
          return (
            <div className="space-y-2">
              <div className="h-3 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                <div className="h-3 w-1/3 animate-pulse rounded-full bg-primary/40" />
              </div>
              <p className="text-sm text-muted-foreground">
                Canlı bağlantı kuruluyor…
              </p>
            </div>
          );
        }
        const pct = Math.max(0, Math.min(100, snapshot.percent));
        const warmingUp = snapshot.processed === 0 && pct < 100;
        const eta =
          snapshot.eta_seconds != null
            ? snapshot.eta_seconds < 90
              ? `~${Math.max(5, Math.round(snapshot.eta_seconds / 5) * 5)} sn kaldı`
              : `~${Math.round(snapshot.eta_seconds / 60)} dk kaldı`
            : null;
        return (
          <div className="space-y-3">
            {/* Büyük yüzde + aşama — net, büyük, anlaşılır. */}
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-2xl font-semibold tabular-nums tracking-tight">
                %{pct.toFixed(0)}
              </p>
              <p className="text-muted-foreground text-sm">
                {stageLabel(pct, snapshot.processed)}
              </p>
            </div>

            <div className="h-3 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
              {warmingUp ? (
                // İlk chunk commit'i gelmeden: kayan şerit. Donmuş
                // %0 bar yerine "çalışıyor" hissi.
                <div className="relative h-3 w-full">
                  <div className="absolute inset-y-0 w-1/3 animate-[progress-slide_1.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-primary/30 via-primary to-primary/30" />
                </div>
              ) : (
                <div
                  className="h-3 rounded-full bg-gradient-to-r from-primary to-[oklch(0.55_0.22_290)] transition-[width] duration-500 [transition-timing-function:var(--motion-ease)]"
                  style={{ width: `${pct}%` }}
                  aria-valuenow={Math.round(pct)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  role="progressbar"
                />
              )}
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
              <span className="tabular-nums">
                {snapshot.processed.toLocaleString("tr-TR")} /{" "}
                {snapshot.total.toLocaleString("tr-TR")} yorum
              </span>
              {snapshot.succeeded > 0 && (
                <span className="text-emerald-700 dark:text-emerald-400 tabular-nums">
                  ✓ {snapshot.succeeded.toLocaleString("tr-TR")} başarılı
                </span>
              )}
              {snapshot.failed > 0 && (
                <span className="text-red-600 dark:text-red-400 tabular-nums">
                  ✗ {snapshot.failed.toLocaleString("tr-TR")} hatalı
                </span>
              )}
              {eta && <span>{eta}</span>}
              {snapshot.tickets_created > 0 && (
                <span className="tabular-nums">
                  {snapshot.tickets_created.toLocaleString("tr-TR")} talep
                  oluşturuldu
                </span>
              )}
            </div>
          </div>
        );
      }}
    </BatchProgressStream>
  );
}
