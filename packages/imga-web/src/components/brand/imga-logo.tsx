// Sprint 10.2 — marka bileşenleri (logo.svg / logo-arma.svg'den).
//
// İki parça:
//   * ImgaMark — arma: birbirine geçen lacivert L-blokları ve tam
//     merkezde turuncu kare. Bloklar currentColor ile boyanır —
//     lacivert sidebar'da beyaz, aydınlık yüzeyde lacivert görünür;
//     merkez kare HER ZAMAN marka turuncusu (sinyal sabittir).
//   * ImgaWordmark — "imga" yazısı. Orijinal logoda turuncu kare,
//     "i"nin noktasıdır; HTML'de noktasız "ı" + üstüne mutlak
//     konumlu turuncu kare ile birebir yeniden kurulur (SVG <text>
//     font bağımlılığı taşımadan, tema renklerine uyumlu).

import { cn } from "@/lib/utils";

const BRAND_ORANGE = "#e26622";

export function ImgaMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 408.58 407.77"
      className={cn("size-6", className)}
      aria-hidden
      focusable="false"
    >
      <polygon
        fill="currentColor"
        points="0 0 0 182.98 96.98 182.98 96.98 100.09 179.19 100.09 179.19 0 0 0"
      />
      <polygon
        fill="currentColor"
        points="303.43 220.84 303.43 306.52 221.65 306.52 221.65 407.77 408.58 407.77 408.58 220.84 303.43 220.84"
      />
      <polygon
        fill="currentColor"
        points="96.98 220.84 11.29 220.84 11.29 388.32 182.67 388.32 182.67 306.53 96.98 306.53 96.98 220.84"
      />
      <polygon
        fill="currentColor"
        points="221.64 18.29 221.64 100.09 307.33 100.09 307.33 185.78 393.01 185.78 393.01 18.29 221.64 18.29"
      />
      <rect x="167.11" y="170.2" width="66.21" height="66.21" fill={BRAND_ORANGE} />
    </svg>
  );
}

export function ImgaWordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-baseline text-xl font-semibold tracking-tight select-none",
        className,
      )}
      aria-label="imga"
    >
      <span className="relative" aria-hidden>
        ı
        <span
          className="absolute left-1/2 top-[0.08em] size-[0.18em] -translate-x-1/2 rounded-[1px]"
          style={{ backgroundColor: BRAND_ORANGE }}
        />
      </span>
      <span aria-hidden>mga</span>
    </span>
  );
}
