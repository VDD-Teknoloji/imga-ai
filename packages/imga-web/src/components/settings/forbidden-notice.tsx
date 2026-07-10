"use client";

import { ShieldAlert } from "lucide-react";

import { useTranslation } from "@/lib/i18n/use-translation";

interface ForbiddenNoticeProps {
  /** HATA-10 — eski sabit metin ayar-sayfası-spesifikti ama tüm
   *  korumalı sayfalarda görünüyordu; RequireRole level'a göre uygun
   *  anahtarı geçer. Default'lar geriye dönük uyumlu. */
  titleKey?: string;
  descKey?: string;
}

export function ForbiddenNotice({
  titleKey = "common.forbidden.title",
  descKey = "common.forbidden.desc",
}: ForbiddenNoticeProps) {
  const { t } = useTranslation();
  return (
    <main className="mx-auto flex w-full max-w-md flex-col items-center gap-3 p-12 text-center">
      <ShieldAlert className="text-muted-foreground size-10" aria-hidden />
      <h1 className="text-2xl font-semibold tracking-tight">{t(titleKey)}</h1>
      <p className="text-muted-foreground text-sm">{t(descKey)}</p>
    </main>
  );
}
