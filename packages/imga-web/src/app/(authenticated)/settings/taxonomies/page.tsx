"use client";

// Sprint 8.3.7-A — /settings/taxonomies.
//
// Edit the per-tenant company-perspective taxonomy. URL-state Path B
// + Suspense (?search, ?show_inactive). System rows
// (is_default_seed=true) can have label / keywords / priority edited
// but cannot be hard-deleted; soft delete (is_active=false) works on
// both system and tenant rows. Drag-reorder via @dnd-kit, optimistic
// at the hook layer.

import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  GripVertical,
  Loader2,
  Plus,
  RotateCcw,
  ShieldCheck,
  Tags,
  Trash2,
  X,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useCreateTaxonomy,
  useDeleteTaxonomy,
  useReorderTaxonomies,
  useRestoreTaxonomy,
  useTaxonomies,
  useUpdateTaxonomy,
} from "@/hooks/use-taxonomies";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { TaxonomyEntry } from "@/lib/types";

const KEYWORD_PREVIEW_LIMIT = 5;
const CODE_REGEX = /^[a-z][a-z0-9_]*$/;

export default function TaxonomiesPage() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <TaxonomiesContent />
    </Suspense>
  );
}

function HeaderSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 p-6 md:p-8">
      <header className="flex items-center gap-2">
        <Tags className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">
            {t("settings.taxonomies.title")}
          </h1>
          <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
        </div>
      </header>
    </main>
  );
}

function TaxonomiesContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { t } = useTranslation();

  // URL-state Path B mirror: useSearchParams stops notifying inside
  // Suspense after first hydration; controlled primitives need a
  // local mirror plus a sync useEffect for back/forward navigation.
  const [search, setSearchState] = useState<string>(
    () => searchParams.get("search") ?? "",
  );
  const [showInactive, setShowInactiveState] = useState<boolean>(
    () => searchParams.get("show_inactive") === "true",
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlSearch = searchParams.get("search") ?? "";
    setSearchState((prev) => (prev === urlSearch ? prev : urlSearch));
    const urlShow = searchParams.get("show_inactive") === "true";
    setShowInactiveState((prev) => (prev === urlShow ? prev : urlShow));
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParam(updates: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") params.delete(key);
      else params.set(key, value);
    }
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const list = useTaxonomies({ include_inactive: showInactive });
  // Wrap the ``data ?? []`` in its own useMemo so the empty-array
  // identity is stable across renders — otherwise the filtered
  // useMemo below sees a fresh ``items`` reference each render and
  // its memoization buys nothing (eslint react-hooks/exhaustive-deps).
  const items = useMemo(() => list.data ?? [], [list.data]);
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return items;
    return items.filter(
      (t) =>
        t.code.toLowerCase().includes(needle) ||
        t.label_tr.toLowerCase().includes(needle),
    );
  }, [items, search]);

  const [editTarget, setEditTarget] = useState<TaxonomyEntry | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 p-6 md:p-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <Tags className="text-primary mt-1 size-6" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
              {t("settings.taxonomies.title")}
            </h1>
            <p className="text-muted-foreground text-sm">
              {t("settings.taxonomies.subtitle")}
            </p>
          </div>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="size-4" aria-hidden /> {t("settings.taxonomies.addCategory")}
        </Button>
      </header>

      <div className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <Input
          value={search}
          onChange={(e) => {
            setSearchState(e.target.value);
            pushParam({ search: e.target.value || null });
          }}
          placeholder={t("settings.taxonomies.searchPlaceholder")}
          className="h-8 max-w-xs"
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => {
              setShowInactiveState(e.target.checked);
              pushParam({
                show_inactive: e.target.checked ? "true" : null,
              });
            }}
            className="size-4"
          />
          {t("settings.taxonomies.showInactive")}
        </label>
        <span className="text-muted-foreground ml-auto text-xs">
          {t("settings.taxonomies.recordCount", { n: filtered.length })}
        </span>
      </div>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : list.isError ? (
        <p className="text-destructive p-6 text-sm">
          {t("settings.taxonomies.loadError")}
        </p>
      ) : filtered.length === 0 ? (
        <div className="bg-card rounded-lg border border-dashed p-8 text-center">
          <p className="text-muted-foreground text-sm">
            {search.trim()
              ? t("settings.taxonomies.noMatch")
              : t("settings.taxonomies.empty")}
          </p>
        </div>
      ) : (
        <TaxonomyList
          // Reorder targets the unfiltered active list to stay coherent
          // with backend priority semantics; if the user is searching
          // we pass a flag to disable drag.
          activeOnly={items.filter((t) => t.is_active)}
          rows={filtered}
          searchActive={search.trim().length > 0 || showInactive}
          onEdit={(t) => setEditTarget(t)}
        />
      )}

      <CreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        existing={items}
      />
      {editTarget && (
        <EditModal
          target={editTarget}
          onClose={() => setEditTarget(null)}
          existing={items}
        />
      )}
    </main>
  );
}

// --- list + drag --------------------------------------------------------

function TaxonomyList({
  activeOnly,
  rows,
  searchActive,
  onEdit,
}: {
  activeOnly: TaxonomyEntry[];
  rows: TaxonomyEntry[];
  searchActive: boolean;
  onEdit: (entry: TaxonomyEntry) => void;
}) {
  const reorder = useReorderTaxonomies();
  const { t } = useTranslation();
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    // Drag is disabled when the list is filtered, but as a defensive
    // guard we still target activeOnly for the reorder payload so a
    // stale render can't accidentally include inactive rows.
    const oldIndex = activeOnly.findIndex((t) => t.id === active.id);
    const newIndex = activeOnly.findIndex((t) => t.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    const next = arrayMove(activeOnly, oldIndex, newIndex);
    reorder.mutate(
      { ordered_ids: next.map((t) => t.id) },
      {
        onError: () => toast.error(t("settings.common.reorderFailed")),
      },
    );
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={onDragEnd}
    >
      <SortableContext
        items={rows.map((t) => t.id)}
        strategy={verticalListSortingStrategy}
      >
        <ul className="space-y-2">
          {rows.map((t) => (
            <SortableRow
              key={t.id}
              entry={t}
              dragDisabled={searchActive || !t.is_active}
              onEdit={() => onEdit(t)}
            />
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}

function SortableRow({
  entry,
  dragDisabled,
  onEdit,
}: {
  entry: TaxonomyEntry;
  dragDisabled: boolean;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: entry.id, disabled: dragDisabled });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`bg-card flex items-start gap-3 rounded-lg border p-3 ${
        entry.is_active ? "" : "opacity-60"
      }`}
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        disabled={dragDisabled}
        className="text-muted-foreground hover:text-foreground mt-1 cursor-grab disabled:cursor-not-allowed disabled:opacity-30"
        aria-label={t("settings.common.dragHandle")}
      >
        <GripVertical className="size-5" aria-hidden />
      </button>
      <TaxonomyRow entry={entry} onEdit={onEdit} />
    </li>
  );
}

function TaxonomyRow({
  entry,
  onEdit,
}: {
  entry: TaxonomyEntry;
  onEdit: () => void;
}) {
  const del = useDeleteTaxonomy();
  const restore = useRestoreTaxonomy();
  const { t } = useTranslation();
  return (
    <div className="flex flex-1 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onEdit}
          className="text-sm font-medium hover:underline"
        >
          {entry.label_tr}
        </button>
        <code className="text-muted-foreground text-xs">{entry.code}</code>
        {entry.is_default_seed && (
          <Badge
            variant="outline"
            className="border-blue-300 bg-blue-50 text-xs text-blue-800"
          >
            <ShieldCheck className="mr-1 size-3" aria-hidden />{" "}
            {t("settings.taxonomies.system")}
          </Badge>
        )}
        {!entry.is_active && (
          <Badge
            variant="outline"
            className="border-zinc-300 bg-zinc-50 text-xs text-zinc-700"
          >
            {t("settings.common.disabled")}
          </Badge>
        )}
        {entry.parent_code && (
          <span className="text-muted-foreground text-xs">
            ↳ {t("settings.taxonomies.parentLabel")}{" "}
            <code>{entry.parent_code}</code>
          </span>
        )}
      </div>
      {entry.keywords.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {entry.keywords.slice(0, KEYWORD_PREVIEW_LIMIT).map((kw) => (
            <span
              key={kw}
              className="bg-muted rounded px-1.5 py-0.5 text-xs"
            >
              {kw}
            </span>
          ))}
          {entry.keywords.length > KEYWORD_PREVIEW_LIMIT && (
            <span className="text-muted-foreground text-xs">
              {t("settings.taxonomies.moreKeywords", {
                n: entry.keywords.length - KEYWORD_PREVIEW_LIMIT,
              })}
            </span>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Button variant="ghost" size="sm" onClick={onEdit}>
          {t("settings.common.edit")}
        </Button>
        {entry.is_active ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={del.isPending}
            onClick={() =>
              del.mutate(entry.id, {
                onSuccess: () =>
                  toast.success(t("settings.taxonomies.deactivated")),
                onError: () => toast.error(t("settings.common.actionFailed")),
              })
            }
            className="gap-1 text-red-700 hover:text-red-900"
          >
            <Trash2 className="size-3.5" aria-hidden />{" "}
            {t("settings.taxonomies.deactivate")}
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            disabled={restore.isPending}
            onClick={() =>
              restore.mutate(entry.id, {
                onSuccess: () =>
                  toast.success(t("settings.taxonomies.restored")),
                onError: () =>
                  toast.error(t("settings.taxonomies.restoreFailed")),
              })
            }
            className="gap-1 text-emerald-700 hover:text-emerald-900"
          >
            <RotateCcw className="size-3.5" aria-hidden />{" "}
            {t("settings.taxonomies.restore")}
          </Button>
        )}
      </div>
    </div>
  );
}

// --- create modal -------------------------------------------------------

function CreateModal({
  open,
  onClose,
  existing,
}: {
  open: boolean;
  onClose: () => void;
  existing: TaxonomyEntry[];
}) {
  const create = useCreateTaxonomy();
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [parentCode, setParentCode] = useState<string>("");

  // Reset on open so reopening starts from a clean form. Same form-
  // mirror pattern as /settings/profile + /settings/integrations.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (open) {
      setCode("");
      setLabel("");
      setKeywords([]);
      setParentCode("");
    }
  }, [open]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const codeValid = code.length === 0 || CODE_REGEX.test(code);
  const codeUnique =
    code.length === 0 || !existing.some((t) => t.code === code);
  const canSubmit =
    !create.isPending &&
    code.length > 0 &&
    codeValid &&
    codeUnique &&
    label.trim().length > 0;

  function onSubmit() {
    if (!canSubmit) return;
    create.mutate(
      {
        code,
        label_tr: label.trim(),
        keywords,
        parent_code: parentCode || null,
      },
      {
        onSuccess: () => {
          toast.success(t("settings.taxonomies.added"));
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            toast.error(err.detail);
            return;
          }
          toast.error(t("settings.taxonomies.addFailed"));
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(v) => (v ? null : onClose())}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("settings.taxonomies.createTitle")}</DialogTitle>
          <DialogDescription>
            {t("settings.taxonomies.createDesc")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="new-code">{t("settings.taxonomies.code")}</Label>
            <Input
              id="new-code"
              value={code}
              onChange={(e) => setCode(e.target.value.trim())}
              placeholder="ornek_kategori"
              maxLength={64}
              aria-invalid={(!codeValid || !codeUnique) || undefined}
            />
            {!codeValid && (
              <p className="text-destructive text-xs">
                {t("settings.taxonomies.codeInvalid")}
              </p>
            )}
            {!codeUnique && (
              <p className="text-destructive text-xs">
                {t("settings.taxonomies.codeInUse")}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="new-label">{t("settings.taxonomies.label")}</Label>
            <Input
              id="new-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={128}
              placeholder={t("settings.taxonomies.labelPlaceholder")}
            />
          </div>

          <KeywordsEditor value={keywords} onChange={setKeywords} />

          <div className="space-y-2">
            <Label htmlFor="new-parent">
              {t("settings.taxonomies.parentCategory")}
            </Label>
            <Select
              value={parentCode || undefined}
              onValueChange={(v) => setParentCode(v ?? "")}
            >
              <SelectTrigger id="new-parent">
                <SelectValue placeholder={t("settings.taxonomies.none")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">{t("settings.taxonomies.none")}</SelectItem>
                {existing
                  .filter((t) => t.is_active && t.code !== code)
                  .map((t) => (
                    <SelectItem key={t.code} value={t.code}>
                      {t.label_tr}{" "}
                      <span className="text-muted-foreground">({t.code})</span>
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={create.isPending}>
            {t("common.cancel")}
          </Button>
          <Button onClick={onSubmit} disabled={!canSubmit} className="gap-2">
            {create.isPending && <Loader2 className="size-4 animate-spin" />}
            {t("settings.common.add")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- edit modal --------------------------------------------------------

function EditModal({
  target,
  onClose,
  existing,
}: {
  target: TaxonomyEntry;
  onClose: () => void;
  existing: TaxonomyEntry[];
}) {
  const update = useUpdateTaxonomy();
  const { t } = useTranslation();
  const [label, setLabel] = useState(target.label_tr);
  const [keywords, setKeywords] = useState<string[]>(target.keywords);
  const [parentCode, setParentCode] = useState<string>(target.parent_code ?? "");

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setLabel(target.label_tr);
    setKeywords(target.keywords);
    setParentCode(target.parent_code ?? "");
  }, [target]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const canSubmit = !update.isPending && label.trim().length > 0;

  function onSubmit() {
    if (!canSubmit) return;
    update.mutate(
      {
        id: target.id,
        body: {
          label_tr: label.trim(),
          keywords,
          parent_code: parentCode || null,
        },
      },
      {
        onSuccess: () => {
          toast.success(t("settings.taxonomies.updated"));
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            toast.error(err.detail);
            return;
          }
          toast.error(t("settings.common.updateFailed"));
        },
      },
    );
  }

  return (
    <Dialog open onOpenChange={(v) => (v ? null : onClose())}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{target.label_tr}</DialogTitle>
          <DialogDescription>
            <code>{target.code}</code>
            {target.is_default_seed && (
              <span className="ml-2 text-blue-700">
                {t("settings.taxonomies.systemCategory")}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="edit-label">{t("settings.taxonomies.label")}</Label>
            <Input
              id="edit-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={128}
            />
          </div>

          <KeywordsEditor value={keywords} onChange={setKeywords} />

          <div className="space-y-2">
            <Label htmlFor="edit-parent">
              {t("settings.taxonomies.parentCategory")}
            </Label>
            <Select
              value={parentCode || undefined}
              onValueChange={(v) => setParentCode(v ?? "")}
            >
              <SelectTrigger id="edit-parent">
                <SelectValue placeholder={t("settings.taxonomies.none")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">{t("settings.taxonomies.none")}</SelectItem>
                {existing
                  .filter(
                    (t) =>
                      t.is_active &&
                      t.code !== target.code &&
                      t.parent_code !== target.code,
                  )
                  .map((t) => (
                    <SelectItem key={t.code} value={t.code}>
                      {t.label_tr}{" "}
                      <span className="text-muted-foreground">({t.code})</span>
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={update.isPending}>
            {t("common.cancel")}
          </Button>
          <Button onClick={onSubmit} disabled={!canSubmit} className="gap-2">
            {update.isPending && <Loader2 className="size-4 animate-spin" />}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- keyword editor ----------------------------------------------------

function KeywordsEditor({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");

  function addOne(raw: string) {
    const cleaned = raw.trim().toLowerCase();
    if (!cleaned) return;
    if (cleaned.length > 64) {
      toast.error(t("settings.taxonomies.keywordTooLong"));
      return;
    }
    if (value.includes(cleaned)) return;
    if (value.length >= 50) {
      toast.error(t("settings.taxonomies.keywordMax"));
      return;
    }
    onChange([...value, cleaned]);
  }

  function addBulk(raw: string) {
    const parts = raw
      .split(/[,\n;]+/)
      .map((p) => p.trim())
      .filter(Boolean);
    if (parts.length <= 1) {
      addOne(parts[0] ?? "");
      return;
    }
    const merged = [...value];
    for (const p of parts) {
      const cleaned = p.toLowerCase();
      if (!cleaned || merged.includes(cleaned) || cleaned.length > 64) continue;
      if (merged.length >= 50) break;
      merged.push(cleaned);
    }
    onChange(merged);
  }

  return (
    <div className="space-y-2">
      <Label>{t("settings.taxonomies.keywords")}</Label>
      <div className="flex flex-wrap items-start gap-2 rounded-md border p-2">
        {value.map((kw) => (
          <span
            key={kw}
            className="bg-muted inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs"
          >
            {kw}
            <button
              type="button"
              onClick={() => onChange(value.filter((x) => x !== kw))}
              className="text-muted-foreground hover:text-destructive"
              aria-label={t("settings.taxonomies.keywordDeleteAria", { kw })}
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addOne(draft);
              setDraft("");
            } else if (e.key === "," && draft.trim()) {
              e.preventDefault();
              addOne(draft);
              setDraft("");
            } else if (e.key === "Backspace" && !draft && value.length > 0) {
              onChange(value.slice(0, -1));
            }
          }}
          onPaste={(e) => {
            const text = e.clipboardData.getData("text");
            if (/[,\n;]/.test(text)) {
              e.preventDefault();
              addBulk(text);
            }
          }}
          onBlur={() => {
            if (draft.trim()) {
              addOne(draft);
              setDraft("");
            }
          }}
          placeholder={
            value.length === 0
              ? t("settings.taxonomies.keywordPlaceholder")
              : ""
          }
          className="min-w-[120px] flex-1 bg-transparent text-xs outline-none"
        />
      </div>
      <p className="text-muted-foreground text-xs">
        {t("settings.taxonomies.keywordHelp", { n: value.length })}
      </p>
    </div>
  );
}
