"use client";

// Sprint 9.0.5-B A — live batch-progress feed.
//
// Subscribes to /tenants/me/analyze/batch/{jobId}/progress (SSE
// backend shipped in Sprint 9.0.5-A R1) and surfaces the latest
// snapshot to the caller. Replaces the 3s polling on
// ``useBatchJob`` for the upload page so the operator sees progress
// flow in real time during the demo's 5K-row run.
//
// The component renders nothing by default — it's a state hook +
// optional ``children`` render-prop so the caller can decide the
// presentation. ``BatchProgressBar`` below is the standard
// renderer the upload page uses.

import { useEffect, useRef, useState } from "react";

import { tokenStorage } from "@/lib/token-storage";
import type { BatchJob } from "@/lib/types";
import { openSseStream, type SseHandle } from "@/lib/sse-client";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

const TERMINAL_STATUSES: ReadonlySet<BatchJob["status"]> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

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

  useEffect(() => {
    if (!jobId) {
      setSnapshot(null);
      setError(null);
      completedRef.current = false;
      return;
    }
    setError(null);
    completedRef.current = false;
    const token = tokenStorage.getAccessToken();
    const url = `${API_BASE}/tenants/me/analyze/batch/${jobId}/progress`;

    const handle = openSseStream(url, {
      token: token ?? null,
      reconnect: true,
      handlers: {
        progress: (payload) => {
          if (payload && typeof payload === "object") {
            setSnapshot(payload as BatchProgressSnapshot);
          }
        },
        complete: (payload) => {
          if (payload && typeof payload === "object") {
            const snap = payload as BatchProgressSnapshot;
            setSnapshot(snap);
            if (
              !completedRef.current &&
              TERMINAL_STATUSES.has(snap.status)
            ) {
              completedRef.current = true;
              onComplete?.(snap);
            }
          }
          handleRef.current?.close();
          handleRef.current = null;
        },
        ping: () => {
          /* keepalive — no UI work */
        },
      },
      onError: (err) => {
        setError(err instanceof Error ? err.message : String(err));
      },
    });
    handleRef.current = handle;
    return () => {
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
