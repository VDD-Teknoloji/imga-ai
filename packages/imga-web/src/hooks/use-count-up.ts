"use client";

// Sprint 10.3 — sayı "dolma" animasyonu. C-level dashboard'da
// büyük sayılar (memnuniyet yüzdesi, yorum adetleri) sıfırdan
// hedefe sayarak açılır — ekran "canlanıyor" hissi verir.
//
// prefers-reduced-motion açıksa animasyon atlanır, hedef direkt
// basılır (globals.css'teki CSS guard JS animasyonlarını kapsamaz;
// burada ayrıca kontrol şart).

import { useEffect, useRef, useState } from "react";

function easeOutQuart(t: number): number {
  return 1 - Math.pow(1 - t, 4);
}

export function useCountUp(target: number, durationMs = 900): number {
  const [value, setValue] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    // Tüm setValue çağrıları rAF callback'inde — render'ı bloklayan
    // senkron set-state yok. Reduced-motion'da t=1 ile tek karede
    // hedefe atlar.
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const start = performance.now();
    function tick(now: number) {
      const t = reduced ? 1 : Math.min(1, (now - start) / durationMs);
      setValue(target * easeOutQuart(t));
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [target, durationMs]);

  return value;
}

/** Mount sonrası true olur — CSS transition'lı genişlik/dolgu
 *  animasyonlarını 0'dan hedefe oynatmak için ("memnuniyet chart'ı
 *  sıfırdan başlayıp dolsun" pattern'inin genel hali). */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);
  return mounted;
}
