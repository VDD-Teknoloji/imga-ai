"use client";

// Sprint 12 — sakin bölüm başlığı.
//
// Apple-vari sadelik için tek tip başlık: düz büyük h2 + isteğe
// bağlı muted alt satır + sağda isteğe bağlı metin-link. Önceki
// nesildeki "gradient kutu içinde ikon" süslemesi kaldırıldı; o
// motif sayfayı "kalabalık / yapay zeka ürünü" gösteriyordu.

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

interface Props {
  title: string;
  description?: string;
  action?: { href: string; label: string };
  children?: ReactNode;
}

export function SectionHeading({ title, description, action, children }: Props) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
      <div className="min-w-0">
        <h2 className="text-xl font-semibold tracking-tight md:text-2xl">
          {title}
        </h2>
        {description && (
          <p className="text-muted-foreground mt-1 text-sm">{description}</p>
        )}
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
