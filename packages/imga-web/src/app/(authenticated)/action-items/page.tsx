"use client";

// Sprint 8.3.10 — /action-items.
//
// Tracks tasks extracted from SWOT recommendations / executive
// briefings or added manually. URL state Path B (?status, ?priority).

import {
  ArchiveRestore,
  History,
  ListChecks,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  useActionItemEvents,
  useActionItems,
  useCreateActionItem,
  useDeleteActionItem,
  useRestoreActionItem,
  useUpdateActionItem,
} from "@/hooks/use-action-items";
import { ApiError, formatApiErrorMessage } from "@/lib/api-client";
import {
  ACTION_ITEM_PRIORITY_LABELS,
  ACTION_ITEM_STATUS_LABELS,
  type ActionItem,
  type ActionItemEvent,
  type ActionItemEventType,
  type ActionItemPriority,
  type ActionItemStatus,
} from "@/lib/types";

const STATUS_TONE: Record<ActionItemStatus, string> = {
  open: "border-blue-300 bg-blue-50 text-blue-800",
  in_progress: "border-amber-300 bg-amber-50 text-amber-800",
  done: "border-emerald-300 bg-emerald-50 text-emerald-800",
  cancelled: "border-zinc-300 bg-zinc-50 text-zinc-700",
};

const PRIORITY_TONE: Record<ActionItemPriority, string> = {
  high: "border-red-300 bg-red-50 text-red-800",
  medium: "border-amber-300 bg-amber-50 text-amber-800",
  low: "border-emerald-300 bg-emerald-50 text-emerald-800",
};

export default function ActionItemsPage() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <Content />
    </Suspense>
  );
}

function HeaderSkeleton() {
  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-center gap-2">
        <ListChecks className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">Aksiyonlar</h1>
          <p className="text-muted-foreground text-sm">Yükleniyor…</p>
        </div>
      </header>
    </main>
  );
}

function Content() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [statusFilter, setStatusFilterState] = useState<ActionItemStatus | "">(
    () => (searchParams.get("status") as ActionItemStatus) || "",
  );
  const [priorityFilter, setPriorityFilterState] = useState<
    ActionItemPriority | ""
  >(() => (searchParams.get("priority") as ActionItemPriority) || "");
  // Sprint 9.1 A — archived toggle state lives in URL params (Path B)
  // so F5 / back / share-link round-trips preserve the choice.
  const [includeArchived, setIncludeArchivedState] = useState<boolean>(
    () => searchParams.get("archived") === "true",
  );
  const [showCreate, setShowCreate] = useState(false);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlStatus =
      (searchParams.get("status") as ActionItemStatus | null) ?? "";
    setStatusFilterState((prev) => (prev === urlStatus ? prev : urlStatus));
    const urlPriority =
      (searchParams.get("priority") as ActionItemPriority | null) ?? "";
    setPriorityFilterState((prev) =>
      prev === urlPriority ? prev : urlPriority,
    );
    const urlArchived = searchParams.get("archived") === "true";
    setIncludeArchivedState((prev) =>
      prev === urlArchived ? prev : urlArchived,
    );
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParam(key: string, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value === null || value === "") params.delete(key);
    else params.set(key, value);
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const list = useActionItems({
    status: statusFilter || undefined,
    priority: priorityFilter || undefined,
    include_archived: includeArchived,
  });

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <ListChecks className="text-primary mt-1 size-6" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
              Aksiyonlar
            </h1>
            <p className="text-muted-foreground text-sm">
              Brifing ve SWOT raporlarından çıkarılan veya manuel
              eklenen takip görevleri.
            </p>
          </div>
        </div>
        <Button onClick={() => setShowCreate(true)} className="gap-2">
          <Plus className="size-4" aria-hidden /> Yeni aksiyon
        </Button>
      </header>

      <div className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <div>
          <Label className="text-xs">Durum</Label>
          <select
            value={statusFilter}
            onChange={(e) => {
              const next = e.target.value as ActionItemStatus | "";
              setStatusFilterState(next);
              pushParam("status", next || null);
            }}
            className="border-input bg-background mt-1 rounded-md border px-2 py-1 text-sm"
          >
            <option value="">Tümü</option>
            {(Object.keys(ACTION_ITEM_STATUS_LABELS) as ActionItemStatus[]).map(
              (s) => (
                <option key={s} value={s}>
                  {ACTION_ITEM_STATUS_LABELS[s]}
                </option>
              ),
            )}
          </select>
        </div>
        <div>
          <Label className="text-xs">Öncelik</Label>
          <select
            value={priorityFilter}
            onChange={(e) => {
              const next = e.target.value as ActionItemPriority | "";
              setPriorityFilterState(next);
              pushParam("priority", next || null);
            }}
            className="border-input bg-background mt-1 rounded-md border px-2 py-1 text-sm"
          >
            <option value="">Tümü</option>
            {(
              Object.keys(ACTION_ITEM_PRIORITY_LABELS) as ActionItemPriority[]
            ).map((p) => (
              <option key={p} value={p}>
                {ACTION_ITEM_PRIORITY_LABELS[p]}
              </option>
            ))}
          </select>
        </div>
        <label className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => {
              const next = e.target.checked;
              setIncludeArchivedState(next);
              pushParam("archived", next ? "true" : null);
            }}
            className="size-3.5"
          />
          Arşivi göster
        </label>
        <span className="text-muted-foreground text-xs">
          {list.data?.length ?? 0} kayıt
        </span>
      </div>

      {showCreate && <CreateForm onClose={() => setShowCreate(false)} />}

      {list.isLoading ? (
        <p className="text-sm">Yükleniyor…</p>
      ) : list.isError ? (
        <p className="text-destructive text-sm">Liste yüklenemedi.</p>
      ) : !list.data || list.data.length === 0 ? (
        <p className="text-muted-foreground p-6 text-center text-sm">
          Aksiyon yok.
        </p>
      ) : (
        <ul className="space-y-2">
          {list.data.map((item) => (
            <ActionItemRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </main>
  );
}

function ActionItemRow({ item }: { item: ActionItem }) {
  const update = useUpdateActionItem();
  const archive = useDeleteActionItem();
  const restore = useRestoreActionItem();
  // Sprint 9.1 A — audit timeline pulls per item-id only when the
  // user expands the row; the route is RLS-bound and cheap enough to
  // not need prefetch.
  const [showHistory, setShowHistory] = useState(false);
  return (
    <li
      className={`rounded-lg border p-3 ${
        item.is_archived
          ? "bg-muted/40 border-dashed opacity-80"
          : "bg-card"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium">{item.title}</p>
        <Badge
          variant="outline"
          className={`text-xs ${PRIORITY_TONE[item.priority]}`}
        >
          {ACTION_ITEM_PRIORITY_LABELS[item.priority]}
        </Badge>
        <Badge
          variant="outline"
          className={`text-xs ${STATUS_TONE[item.status]}`}
        >
          {ACTION_ITEM_STATUS_LABELS[item.status]}
        </Badge>
        {item.is_archived && (
          <Badge
            variant="outline"
            className="border-zinc-400 bg-zinc-100 text-xs text-zinc-700"
          >
            Arşivde
          </Badge>
        )}
        {item.source_report_id && (
          <span className="text-muted-foreground text-xs">
            kaynak: SWOT
          </span>
        )}
        {item.source_briefing_id && (
          <span className="text-muted-foreground text-xs">
            kaynak: Brifing
          </span>
        )}
      </div>
      <p className="text-muted-foreground mt-1 text-sm">{item.description}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {!item.is_archived && (
          <select
            value={item.status}
            onChange={(e) =>
              update.mutate({
                id: item.id,
                body: { status: e.target.value as ActionItemStatus },
              })
            }
            className="border-input bg-background rounded-md border px-2 py-1"
          >
            {(
              Object.keys(ACTION_ITEM_STATUS_LABELS) as ActionItemStatus[]
            ).map((s) => (
              <option key={s} value={s}>
                {ACTION_ITEM_STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowHistory((v) => !v)}
          className="gap-1"
        >
          <History className="size-3.5" aria-hidden />
          {showHistory ? "Geçmişi gizle" : "Geçmiş"}
        </Button>
        {item.is_archived ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={restore.isPending}
            onClick={() =>
              restore.mutate(item.id, {
                onSuccess: () => toast.success("Geri alındı."),
                onError: (err) => toast.error(formatApiErrorMessage(err)),
              })
            }
            className="gap-1 text-emerald-700 hover:text-emerald-900"
          >
            <ArchiveRestore className="size-3.5" aria-hidden /> Geri al
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            disabled={archive.isPending}
            onClick={() => {
              if (confirm("Aksiyon arşivlensin mi? (Geri alınabilir)")) {
                archive.mutate(item.id, {
                  onSuccess: () => toast.success("Arşivlendi."),
                  onError: (err) => toast.error(formatApiErrorMessage(err)),
                });
              }
            }}
            className="gap-1 text-red-700 hover:text-red-900"
          >
            <Trash2 className="size-3.5" aria-hidden /> Arşivle
          </Button>
        )}
      </div>
      {showHistory && <AuditTimeline itemId={item.id} />}
    </li>
  );
}

const EVENT_LABELS: Record<ActionItemEventType, string> = {
  created: "Oluşturuldu",
  updated: "Güncellendi",
  archived: "Arşivlendi",
  unarchived: "Geri alındı",
  status_changed: "Durum değişti",
  priority_changed: "Öncelik değişti",
  assigned: "Atandı",
  unassigned: "Atama kaldırıldı",
  commented: "Yorum eklendi",
};

function AuditTimeline({ itemId }: { itemId: string }) {
  const events = useActionItemEvents(itemId);
  if (events.isLoading) {
    return (
      <div className="text-muted-foreground mt-3 flex items-center gap-2 border-t pt-3 text-xs">
        <Loader2 className="size-3 animate-spin" /> Geçmiş yükleniyor…
      </div>
    );
  }
  if (events.isError) {
    return (
      <p className="text-destructive mt-3 border-t pt-3 text-xs">
        Geçmiş yüklenemedi.
      </p>
    );
  }
  const list = events.data ?? [];
  if (list.length === 0) {
    return (
      <p className="text-muted-foreground mt-3 border-t pt-3 text-xs">
        Olay yok.
      </p>
    );
  }
  return (
    <ol className="mt-3 space-y-1.5 border-t pt-3 text-xs">
      {list.map((evt) => (
        <li key={evt.id} className="flex items-baseline gap-2">
          <span className="text-muted-foreground tabular-nums">
            {new Date(evt.created_at).toLocaleString("tr-TR")}
          </span>
          <span className="font-medium">{EVENT_LABELS[evt.event_type]}</span>
          <AuditPayloadSummary event={evt} />
        </li>
      ))}
    </ol>
  );
}

function AuditPayloadSummary({ event }: { event: ActionItemEvent }) {
  const p = event.payload ?? {};
  const summary = formatPayloadSummary(event.event_type, p);
  return (
    <span className="text-muted-foreground">
      {summary && <span>{summary} · </span>}
      <span className="text-[10px] uppercase">{event.actor_type}</span>
    </span>
  );
}

function formatPayloadSummary(
  type: ActionItemEventType,
  payload: Record<string, unknown>,
): string | null {
  if (type === "status_changed" || type === "priority_changed") {
    const from = payload.from;
    const to = payload.to;
    if (from !== undefined && to !== undefined) {
      return `${String(from ?? "—")} → ${String(to ?? "—")}`;
    }
  }
  if (type === "assigned" && typeof payload.to === "string") {
    return `→ ${payload.to.slice(0, 8)}`;
  }
  return null;
}

function CreateForm({ onClose }: { onClose: () => void }) {
  const create = useCreateActionItem();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<ActionItemPriority>("medium");

  function onSubmit() {
    if (!title.trim() || !description.trim()) {
      toast.error("Başlık ve açıklama zorunlu.");
      return;
    }
    create.mutate(
      {
        title: title.trim(),
        description: description.trim(),
        priority,
      },
      {
        onSuccess: () => {
          toast.success("Aksiyon eklendi.");
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError) toast.error(err.detail);
          else toast.error("Eklenemedi.");
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Yeni Aksiyon</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <Label className="text-xs">Başlık</Label>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={256}
          />
        </div>
        <div>
          <Label className="text-xs">Açıklama</Label>
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </div>
        <div>
          <Label className="text-xs">Öncelik</Label>
          <select
            value={priority}
            onChange={(e) =>
              setPriority(e.target.value as ActionItemPriority)
            }
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          >
            {(
              Object.keys(ACTION_ITEM_PRIORITY_LABELS) as ActionItemPriority[]
            ).map((p) => (
              <option key={p} value={p}>
                {ACTION_ITEM_PRIORITY_LABELS[p]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={create.isPending}
          >
            İptal
          </Button>
          <Button
            onClick={onSubmit}
            disabled={create.isPending}
            className="gap-2"
          >
            {create.isPending && <Loader2 className="size-4 animate-spin" />}
            Ekle
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
