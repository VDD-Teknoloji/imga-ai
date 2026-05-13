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

/**
 * Default progress renderer used by /analyze/upload. Shows a bar +
 * processed/total + ETA. Caller can build their own UI by passing
 * a ``children`` prop to ``BatchProgressStream`` directly instead.
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
            <div className="text-sm text-muted-foreground">
              Canlı ilerleme bağlantısı kuruluyor…
            </div>
          );
        }
        const pct = Math.max(0, Math.min(100, snapshot.percent));
        const eta =
          snapshot.eta_seconds != null
            ? `Kalan ~${Math.max(1, Math.round(snapshot.eta_seconds / 60))} dk`
            : null;
        return (
          <div className="space-y-2">
            <div className="h-2 w-full rounded-full bg-zinc-200 dark:bg-zinc-800">
              <div
                className="h-2 rounded-full bg-blue-600 transition-[width] duration-300"
                style={{ width: `${pct}%` }}
                aria-valuenow={Math.round(pct)}
                aria-valuemin={0}
                aria-valuemax={100}
                role="progressbar"
              />
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
              <span>
                {snapshot.processed.toLocaleString("tr-TR")} /{" "}
                {snapshot.total.toLocaleString("tr-TR")} yorum
              </span>
              <span>%{pct.toFixed(1)}</span>
              {eta && <span>{eta}</span>}
              {snapshot.tickets_created > 0 && (
                <span>
                  {snapshot.tickets_created.toLocaleString("tr-TR")}{" "}
                  bilet oluşturuldu
                </span>
              )}
            </div>
          </div>
        );
      }}
    </BatchProgressStream>
  );
}
