"use client";

// Sprint 12 — sakin bölüm başlığı.
//
// Apple-vari sadelik için tek tip başlık: düz büyük h2 + isteğe
// bağlı muted alt satır + sağda isteğe bağlı metin-link. Önceki
// nesildeki "gradient kutu içinde ikon" süslemesi kaldırıldı; o
// motif sayfayı "kalabalık / yapay zeka ürünü" gösteriyordu.

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  title: string;
  description?: string;
  action?: { href: string; label: string };
  /** F (2026-09-02, home-liveliness) — isteğe bağlı küçük ikon slotu;
   *  görev talimatı "may get" diyor — varsayılan yok, hiçbir mevcut
   *  çağrı yeri etkilenmez. */
  icon?: LucideIcon;
  children?: ReactNode;
}

export function SectionHeading({ title, description, action, icon: Icon, children }: Props) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight md:text-2xl">
          {Icon && (
            <span className="bg-muted text-muted-foreground inline-flex size-7 shrink-0 items-center justify-center rounded-lg">
              <Icon className="size-4" aria-hidden />
            </span>
          )}
          {title}
        </h2>
        {description && <p className="text-muted-foreground mt-1 text-sm">{description}</p>}
      </div>
      {action && (
        <Link
          href={action.href}
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm font-medium transition-colors"
        >
          {action.label}
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      )}
      {children}
    </div>
  );
}
