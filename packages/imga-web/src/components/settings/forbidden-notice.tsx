"use client";

import { ShieldAlert } from "lucide-react";

import { useTranslation } from "@/lib/i18n/use-translation";

export function ForbiddenNotice() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto flex w-full max-w-md flex-col items-center gap-3 p-12 text-center">
      <ShieldAlert className="text-muted-foreground size-10" aria-hidden />
      <h1 className="text-2xl font-semibold tracking-tight">
        {t("common.forbidden.title")}
      </h1>
      <p className="text-muted-foreground text-sm">
        {t("common.forbidden.desc")}
      </p>
    </main>
  );
}
