import { forwardRef } from "react";
import type { LucideIcon, LucideProps } from "lucide-react";

// lucide-react marka ikonlarını kaldırdı (Twitter dahil); nav-config
// LucideIcon imzası beklediği için X logosunu aynı sözleşmeyle yerelde
// çiziyoruz. stroke tabanlı lucide'ın aksine dolgu (fill) kullanır —
// logo tek parça bir glif.
export const XLogo: LucideIcon = forwardRef<
  SVGSVGElement,
  Omit<LucideProps, "ref">
>(function XLogo(
  { color = "currentColor", size = 24, strokeWidth: _sw, absoluteStrokeWidth: _asw, ...rest },
  ref,
) {
  return (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={color}
      stroke="none"
      {...rest}
    >
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231 5.451-6.231Zm-1.161 17.52h1.833L7.084 4.126H5.117l11.966 15.644Z" />
    </svg>
  );
});
