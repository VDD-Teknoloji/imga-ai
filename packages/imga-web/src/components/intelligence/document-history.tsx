"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useIntelligenceQuery, useIntelligenceUrl } from "@/hooks/use-intelligence";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { DocumentSnapshot } from "@/lib/intelligence-types";
import { ErrorMessage, Loading } from "./fields";

export function DocumentHistory<T>({
  kind,
  render,
}: {
  kind: "prd" | "company";
  render: (content: T) => ReactNode;
}) {
  const { t } = useTranslation();
  const { params, change } = useIntelligenceUrl();
  const cursor = Number(params.get("history_before"));
  const before = Number.isSafeInteger(cursor) && cursor > 0 ? cursor : null;
  const setBefore = (value: number | null) =>
    change({ history_before: value ? String(value) : "" });
  const query = useIntelligenceQuery<DocumentSnapshot<T>[]>(
    `/documents/${kind}/history${before ? `?before=${before}` : ""}`,
  );
  if (query.isLoading) return <Loading />;
  return (
    <section className="space-y-3">
      <ErrorMessage error={query.error} />
      {query.data?.length === 0 && <p>{t("intel.empty")}</p>}
      {query.data?.map((snapshot) => (
        <details key={snapshot.revision} className="border-b py-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t("intel.revision")} {snapshot.revision} · {t(`intel.${snapshot.status}`)} ·{" "}
            {snapshot.created_at ? new Date(snapshot.created_at).toLocaleString() : ""}
          </summary>
          <div className="space-y-4 py-4 text-sm">{render(snapshot.content)}</div>
        </details>
      ))}
      <div className="flex gap-2">
        {before && (
          <Button variant="outline" onClick={() => setBefore(null)}>
            {t("intel.current")}
          </Button>
        )}
        {query.data?.length === 20 && (
          <Button variant="outline" onClick={() => setBefore(query.data?.at(-1)?.revision ?? null)}>
            {t("intel.older")}
          </Button>
        )}
      </div>
    </section>
  );
}
