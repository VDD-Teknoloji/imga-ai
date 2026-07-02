"use client";

import { ChevronLeft, Loader2, Upload } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useBatchHistory } from "@/hooks/use-batch-uploads";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { BatchJobStatus } from "@/lib/types";

const STATUS_LABEL_KEYS: Record<BatchJobStatus, string> = {
  queued: "analyze.history.status.queued",
  processing: "analyze.history.status.processing",
  completed: "analyze.history.status.completed",
  failed: "analyze.history.status.failed",
  cancelled: "analyze.history.status.cancelled",
};

const STATUS_TONES: Record<BatchJobStatus, "default" | "success" | "danger" | "warning"> = {
  queued: "default",
  processing: "warning",
  completed: "success",
  failed: "danger",
  cancelled: "default",
};

export default function BatchHistoryPage() {
  const { t } = useTranslation();
  const history = useBatchHistory(50);
  const jobs = history.data?.pages.flatMap((p) => p.jobs) ?? [];

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8">
      <header className="flex items-center justify-between gap-4">
        <div className="space-y-1">
          <Link
            href="/analyze/upload"
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
          >
            <ChevronLeft className="size-4" /> {t("analyze.history.backUpload")}
          </Link>
          <h1 className="text-2xl font-semibold">{t("analyze.history.title")}</h1>
        </div>
        <Button render={<Link href="/analyze/upload" />}>
          <Upload className="size-4" /> {t("analyze.history.newUpload")}
        </Button>
      </header>

      {history.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("analyze.history.loading")}
        </div>
      ) : jobs.length === 0 ? (
        <p className="text-muted-foreground p-6 text-sm">
          {t("analyze.history.emptyBefore")}
          <Link href="/analyze/upload" className="underline">
            {t("analyze.history.emptyLink")}
          </Link>
          {t("analyze.history.emptyAfter")}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("analyze.history.col.date")}</TableHead>
              <TableHead>{t("analyze.history.col.file")}</TableHead>
              <TableHead className="hidden text-right md:table-cell">{t("analyze.history.col.rows")}</TableHead>
              <TableHead>{t("analyze.history.col.status")}</TableHead>
              <TableHead className="hidden text-right md:table-cell">{t("analyze.history.col.succeeded")}</TableHead>
              <TableHead className="hidden text-right md:table-cell">{t("analyze.history.col.failed")}</TableHead>
              <TableHead className="hidden text-right md:table-cell">{t("analyze.history.col.tickets")}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => {
              const tone = STATUS_TONES[job.status];
              return (
                <TableRow key={job.job_id}>
                  <TableCell className="text-muted-foreground text-xs">
                    {new Date(job.created_at).toLocaleString("tr-TR")}
                  </TableCell>
                  <TableCell className="max-w-xs truncate font-medium">
                    {job.file_name}
                  </TableCell>
                  <TableCell className="hidden text-right md:table-cell">
                    {job.total_rows}
                  </TableCell>
                  <TableCell>
                    <Badge variant={tone === "default" ? "outline" : undefined}>
                      {t(STATUS_LABEL_KEYS[job.status])}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden text-right md:table-cell">
                    {job.succeeded_rows}
                  </TableCell>
                  <TableCell className="hidden text-right md:table-cell">
                    {job.failed_rows}
                  </TableCell>
                  <TableCell className="hidden text-right md:table-cell">
                    {job.tickets_created}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="link"
                      className="h-auto p-0"
                      render={<Link href={`/reviews?batch_job_id=${job.job_id}`} />}
                    >
                      {t("analyze.history.viewAnalyses")}
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      {history.hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => history.fetchNextPage()}
            disabled={history.isFetchingNextPage}
          >
            {history.isFetchingNextPage ? t("analyze.history.loading") : t("analyze.history.loadMore")}
          </Button>
        </div>
      )}
    </main>
  );
}
