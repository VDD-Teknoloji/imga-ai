"use client";

// Sprint 13 — toplu yükleme barının "sürekli akış" hissi.
//
// Gerçek ilerleme kareleri chunk sonunda gelir (worker chunk_size=200
// satırda bir commit/publish eder); büyük dosyada bar dakikalarca
// donmuş görünüyordu. Bu hook gerçek yüzde kareleri ARASINDA tahmini
// hızla ilerleyen bir görüntü yüzdesi üretir:
//
//   * hız: canlı eta_seconds'tan (kalan yüzde / kalan saniye) ya da
//     son iki gerçek kare arasındaki delta'dan türetilir,
//   * tahmin bir sonraki beklenen gerçek değerin ~%2 altında
//     asimptotik yavaşlayarak clamp'lenir (asla geri gitmez, asla
//     gerçeği sollamaz),
//   * yeni gerçek kare gelince görüntü ona anında yakalar.
//
// prefers-reduced-motion açıksa interpolasyon atlanır, gerçek yüzde
// olduğu gibi döner (use-count-up.ts'teki guard kalıbı).

import { useEffect, useRef, useState } from "react";

// Kare hiç gelmemişken / delta ölçülememişken kullanılan taban hız —
// bar en baştan itibaren gözle görülür kıpırdasın diye sıfırdan büyük.
const FALLBACK_RATE_PCT_PER_SEC = 0.4;
// İlk gerçek kareden önce varsayılan sıçrama beklentisi (yüzde puanı).
const FALLBACK_CHUNK_PCT = 10;
// Tahmin, beklenen bir sonraki gerçek değerin bu kadar altında durur.
const CLAMP_MARGIN_PCT = 2;

/**
 * @param realPercent 0-100 arası gerçek (otoriter) yüzde.
 * @param etaSeconds  Canlı SSE karesinden kalan süre; yoksa null.
 * @param active      İş koşuyor mu — false ise gerçek yüzde döner.
 */
export function useSmoothProgress(
  realPercent: number,
  etaSeconds: number | null | undefined,
  active: boolean,
): number {
  const [display, setDisplay] = useState(realPercent);
  const displayRef = useRef(realPercent);
  const lastRealRef = useRef(realPercent);
  const lastDeltaRef = useRef<number>(FALLBACK_CHUNK_PCT);
  const etaRef = useRef<number | null>(null);

  useEffect(() => {
    etaRef.current = etaSeconds ?? null;
  }, [etaSeconds]);

  // Gerçek kare değişimini yakala: hız ölçümü için delta kaydet,
  // görüntüyü anında yeni gerçeğe yakala (geri gitme yok).
  useEffect(() => {
    const prev = lastRealRef.current;
    if (realPercent !== prev) {
      if (realPercent > prev) lastDeltaRef.current = realPercent - prev;
      lastRealRef.current = realPercent;
    }
    if (realPercent > displayRef.current || !active) {
      displayRef.current = realPercent;
      setDisplay(realPercent);
    }
  }, [realPercent, active]);

  useEffect(() => {
    if (!active) return;
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduced) return;

    let raf = 0;
    let prevTick = performance.now();
    function tick(now: number) {
      const dt = (now - prevTick) / 1000;
      prevTick = now;
      const real = lastRealRef.current;
      const ceiling = Math.min(
        99,
        real + Math.max(lastDeltaRef.current, CLAMP_MARGIN_PCT + 1) - CLAMP_MARGIN_PCT,
      );
      const eta = etaRef.current;
      const rate =
        eta !== null && eta > 0
          ? Math.max((100 - real) / eta, FALLBACK_RATE_PCT_PER_SEC / 4)
          : FALLBACK_RATE_PCT_PER_SEC;
      const current = displayRef.current;
      if (current < ceiling) {
        // Tavana yaklaştıkça asimptotik yavaşla — bar durmaz ama
        // gerçek kareden önce tavanı delmez.
        const headroom = Math.max(0, (ceiling - current) / Math.max(ceiling - real, 0.001));
        const next = Math.min(ceiling, current + rate * dt * Math.max(headroom, 0.05));
        if (next > current) {
          displayRef.current = next;
          // 0.1 puana yuvarla — aynı değerde React render'ı atlar,
          // 60fps'lik rAF döngüsü gereksiz re-render üretmez.
          setDisplay(Math.round(next * 10) / 10);
        }
      }
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active]);

  if (!active) return realPercent;
  return Math.max(display, realPercent);
}
