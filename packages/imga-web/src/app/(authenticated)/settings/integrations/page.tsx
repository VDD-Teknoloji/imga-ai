"use client";

// Sprint 8.3.6.6 — /settings/integrations.
//
// Tenant Gemini API key management. Drag-reorder via @dnd-kit;
// optimistic update at the hook layer (use-llm-credentials.ts) so
// the drag UX feels instant + rollback on backend failure.
//
// Security UX: full plaintext lives only inside the Add form.
// On submit, the response only carries the last-4 preview ("...AB12");
// the form clears the input so the page never re-renders the secret.

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
  AlertTriangle,
  Check,
  ChevronsUpDown,
  Eye,
  EyeOff,
  GripVertical,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  useCreateLlmCredential,
  useDeleteLlmCredential,
  useLlmCredentials,
  useOpenRouterModels,
  useReorderLlmCredentials,
  useUpdateLlmCredential,
} from "@/hooks/use-llm-credentials";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { LlmCredential, LlmProviderName } from "@/lib/types";
import { cn } from "@/lib/utils";

const GEMINI_KEY_PREFIX = "AIza";
const OPENROUTER_KEY_PREFIX = "sk-or-";

const PROVIDER_BADGE: Record<string, string> = {
  gemini: "Gemini",
  openrouter: "OpenRouter",
};

/** Aranabilir OpenRouter model secicisi — hem Add formu hem satir ici
 *  degisiklik ayni bileseni kullanir. Katalog canli endpoint'ten gelir
 *  (kuratorlu onerilenler ustte); yeni model ciktiginda kod degisikligi
 *  gerekmez. */
function ModelPicker({
  value,
  onSelect,
  disabled,
  compact,
}: {
  value: string | null;
  onSelect: (model: string | null) => void;
  disabled?: boolean;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const catalog = useOpenRouterModels(open);
  const models = catalog.data?.models ?? [];
  const recommended = models.filter((m) => m.recommended);
  const others = models.filter((m) => !m.recommended);

  function pick(model: string | null) {
    onSelect(model);
    setOpen(false);
  }

  function priceHint(prompt: number | null, completion: number | null) {
    if (prompt === null || completion === null) return null;
    return `$${prompt.toFixed(2)} / $${completion.toFixed(2)} · 1M`;
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            className={cn(
              "justify-between gap-2 font-normal",
              compact ? "h-7 max-w-[260px] px-2 text-xs" : "w-full",
            )}
          >
            <span className="truncate font-mono">
              {value ?? t("settings.integrations.modelDefault")}
            </span>
            <ChevronsUpDown className="size-3.5 shrink-0 opacity-60" aria-hidden />
          </Button>
        }
      />
      <PopoverContent align="start" className="w-[340px] p-0">
        <Command>
          <CommandInput
            placeholder={t("settings.integrations.modelSearchPlaceholder")}
          />
          <CommandList className="max-h-[320px]">
            <CommandEmpty>
              {catalog.isLoading
                ? t("common.loading")
                : t("settings.integrations.modelEmpty")}
            </CommandEmpty>
            <CommandGroup>
              <CommandItem
                value="__default__ varsayilan default"
                onSelect={() => pick(null)}
                className="flex items-center justify-between gap-2"
              >
                <span>{t("settings.integrations.modelDefault")}</span>
                {value === null && (
                  <Check className="text-primary size-4" aria-hidden />
                )}
              </CommandItem>
            </CommandGroup>
            {recommended.length > 0 && (
              <CommandGroup
                heading={t("settings.integrations.modelRecommended")}
              >
                {recommended.map((m) => (
                  <CommandItem
                    key={m.id}
                    value={m.id}
                    onSelect={() => pick(m.id)}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-mono text-xs">{m.id}</span>
                      <span className="text-muted-foreground text-[10px]">
                        {priceHint(
                          m.prompt_price_per_million,
                          m.completion_price_per_million,
                        )}
                      </span>
                    </span>
                    {value === m.id && (
                      <Check className="text-primary size-4 shrink-0" aria-hidden />
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {others.length > 0 && (
              <CommandGroup heading={t("settings.integrations.modelAll")}>
                {others.map((m) => (
                  <CommandItem
                    key={m.id}
                    value={m.id}
                    onSelect={() => pick(m.id)}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-mono text-xs">{m.id}</span>
                      <span className="text-muted-foreground text-[10px]">
                        {priceHint(
                          m.prompt_price_per_million,
                          m.completion_price_per_million,
                        )}
                      </span>
                    </span>
                    {value === m.id && (
                      <Check className="text-primary size-4 shrink-0" aria-hidden />
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export default function IntegrationsPage() {
  return (
    <RequireRole level="admin">
      <IntegrationsPageInner />
    </RequireRole>
  );
}

function IntegrationsPageInner() {
  const list = useLlmCredentials();
  const credentials = list.data ?? [];
  const { t } = useTranslation();

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("settings.integrations.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("settings.integrations.subtitle")}
        </p>
      </header>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : list.isError ? (
        <p className="text-destructive p-6 text-sm">
          {t("settings.integrations.loadError")}
        </p>
      ) : credentials.length === 0 ? (
        <EmptyState />
      ) : (
        <KeyList credentials={credentials} />
      )}

      <AddKeyForm />
    </main>
  );
}

function EmptyState() {
  const { t } = useTranslation();
  return (
    <div className="bg-card rounded-lg border border-dashed p-8 text-center">
      <p className="text-muted-foreground text-sm">
        {t("settings.integrations.empty")}
      </p>
    </div>
  );
}

function KeyList({ credentials }: { credentials: LlmCredential[] }) {
  const reorder = useReorderLlmCredentials();
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
    const oldIndex = credentials.findIndex((c) => c.id === active.id);
    const newIndex = credentials.findIndex((c) => c.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    const next = arrayMove(credentials, oldIndex, newIndex);
    reorder.mutate(
      { ordered_ids: next.map((c) => c.id) },
      {
        onError: () => {
          toast.error(t("settings.common.reorderFailed"));
        },
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
        items={credentials.map((c) => c.id)}
        strategy={verticalListSortingStrategy}
      >
        <ul className="space-y-2">
          {credentials.map((cred, idx) => (
            <SortableKeyRow key={cred.id} credential={cred} index={idx} />
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}

function SortableKeyRow({
  credential,
  index,
}: {
  credential: LlmCredential;
  index: number;
}) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: credential.id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <li
      ref={setNodeRef}
      style={style}
      className="bg-card flex items-center gap-3 rounded-lg border p-3"
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        className="text-muted-foreground hover:text-foreground cursor-grab"
        aria-label={t("settings.common.dragHandle")}
      >
        <GripVertical className="size-5" aria-hidden />
      </button>
      <KeyRow credential={credential} index={index} />
    </li>
  );
}

function KeyRow({
  credential,
  index,
}: {
  credential: LlmCredential;
  index: number;
}) {
  const update = useUpdateLlmCredential();
  const del = useDeleteLlmCredential();
  const { t } = useTranslation();
  const [label, setLabel] = useState(credential.label);
  const [editing, setEditing] = useState(false);

  // Reorder + refetch can replace the underlying credential while a
  // row is mounted; sync the editable mirror back to the server value.
  // Same form-mirror pattern as /settings/profile.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setLabel(credential.label);
  }, [credential.label]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function commitLabel() {
    setEditing(false);
    if (label.trim() && label.trim() !== credential.label) {
      update.mutate(
        { id: credential.id, body: { label: label.trim() } },
        {
          onError: () => {
            toast.error(t("settings.integrations.labelUpdateFailed"));
            setLabel(credential.label);
          },
        },
      );
    } else {
      setLabel(credential.label);
    }
  }

  return (
    <div className="flex flex-1 items-center gap-3">
      <div className="flex-1 space-y-1">
        <div className="flex items-center gap-2">
          {editing ? (
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              onBlur={commitLabel}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitLabel();
                if (e.key === "Escape") {
                  setLabel(credential.label);
                  setEditing(false);
                }
              }}
              autoFocus
              className="h-7 max-w-[200px] text-sm"
            />
          ) : (
            <button
              type="button"
              className="text-sm font-medium hover:underline"
              onClick={() => setEditing(true)}
              title={t("settings.integrations.editLabel")}
            >
              {credential.label}
            </button>
          )}
          <Badge variant="outline" className="text-xs">
            {index === 0
              ? t("settings.integrations.primary")
              : t("settings.integrations.backup", { n: index })}
          </Badge>
          <Badge
            variant="outline"
            className={cn(
              "text-xs",
              credential.provider === "openrouter"
                ? "border-violet-300 bg-violet-50 text-violet-700"
                : "border-sky-300 bg-sky-50 text-sky-700",
            )}
          >
            {PROVIDER_BADGE[credential.provider] ?? credential.provider}
          </Badge>
          {credential.last_failed_at && (
            <Badge
              variant="outline"
              className="border-amber-400 bg-amber-50 text-xs text-amber-700"
              title={t("settings.integrations.lastFailed", {
                date: new Date(credential.last_failed_at).toLocaleString("tr-TR"),
              })}
            >
              <AlertTriangle className="mr-1 size-3" aria-hidden />
              {t("settings.integrations.warning")}
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground font-mono text-xs">
          {credential.value_preview}
        </p>
        {credential.provider === "openrouter" && (
          <div className="pt-1">
            <ModelPicker
              compact
              value={credential.model}
              disabled={update.isPending}
              onSelect={(model) => {
                if ((model ?? null) === (credential.model ?? null)) return;
                update.mutate(
                  {
                    id: credential.id,
                    body: { model },
                  },
                  {
                    onSuccess: () =>
                      toast.success(t("settings.integrations.modelChanged")),
                    onError: () =>
                      toast.error(
                        t("settings.integrations.modelChangeFailed"),
                      ),
                  },
                );
              }}
            />
          </div>
        )}
      </div>
      <Switch
        checked={credential.is_active}
        onCheckedChange={(checked) =>
          update.mutate(
            { id: credential.id, body: { is_active: checked } },
            {
              onError: () => toast.error(t("settings.integrations.statusUpdateFailed")),
            },
          )
        }
        aria-label={t("settings.integrations.toggleActive")}
      />
      <DeleteKeyButton
        label={credential.label}
        pending={del.isPending}
        onConfirm={() =>
          del.mutate(credential.id, {
            onSuccess: () => toast.success(t("settings.integrations.keyDeleted")),
            onError: () => toast.error(t("settings.integrations.deleteFailed")),
          })
        }
      />
    </div>
  );
}

function DeleteKeyButton({
  label,
  pending,
  onConfirm,
}: {
  label: string;
  pending: boolean;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            disabled={pending}
            aria-label={t("settings.integrations.deleteAria", { label })}
          >
            <Trash2 className="size-4" />
          </Button>
        }
      />
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t("settings.integrations.deleteConfirmTitle")}
          </AlertDialogTitle>
          <AlertDialogDescription>
            <span className="font-medium">{label}</span>{" "}
            {t("settings.integrations.deleteConfirmDesc")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              onConfirm();
              setOpen(false);
            }}
          >
            {t("settings.common.delete")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function AddKeyForm() {
  const create = useCreateLlmCredential();
  const { t } = useTranslation();
  // Yeni eklemelerde varsayilan OpenRouter (urun karari — "Gemini
  // yerine OpenRouter"): mevcut Gemini kayitlari calismaya devam eder.
  const [provider, setProvider] = useState<LlmProviderName>("openrouter");
  const [model, setModel] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [reveal, setReveal] = useState(false);

  const trimmed = apiKey.trim();
  const expectedPrefix =
    provider === "gemini" ? GEMINI_KEY_PREFIX : OPENROUTER_KEY_PREFIX;
  const keyPrefixOk =
    trimmed.length === 0 || trimmed.startsWith(expectedPrefix);
  const canSubmit =
    !create.isPending &&
    label.trim().length > 0 &&
    trimmed.length >= 10 &&
    keyPrefixOk;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    create.mutate(
      {
        label: label.trim(),
        api_key: trimmed,
        provider,
        model: provider === "openrouter" ? model : null,
      },
      {
        onSuccess: () => {
          // Clear plaintext immediately so a screenshare or scroll-up
          // can't surface the key.
          setLabel("");
          setApiKey("");
          setModel(null);
          setReveal(false);
          toast.success(t("settings.integrations.keyAdded"));
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400) {
            toast.error(err.detail);
            return;
          }
          toast.error(t("settings.integrations.addFailed"));
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="bg-card space-y-3 rounded-lg border p-4">
      <h2 className="text-base font-semibold">
        {t("settings.integrations.addTitle")}
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="key-provider">
            {t("settings.integrations.providerField")}
          </Label>
          <Select
            value={provider}
            onValueChange={(v) => {
              if (v === "gemini" || v === "openrouter") {
                setProvider(v);
                setModel(null);
              }
            }}
          >
            <SelectTrigger id="key-provider" disabled={create.isPending}>
              <SelectValue>
                {(value: string | null) =>
                  PROVIDER_BADGE[value ?? provider] ?? value
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="openrouter">OpenRouter</SelectItem>
              <SelectItem value="gemini">Gemini</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {provider === "openrouter" && (
          <div className="space-y-2">
            <Label>{t("settings.integrations.modelField")}</Label>
            <ModelPicker
              value={model}
              onSelect={setModel}
              disabled={create.isPending}
            />
          </div>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="key-label">{t("settings.integrations.labelField")}</Label>
        <Input
          id="key-label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={t("settings.integrations.labelPlaceholder")}
          maxLength={64}
          disabled={create.isPending}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="key-value">{t("settings.integrations.apiKeyField")}</Label>
        <div className="flex gap-2">
          <Input
            id="key-value"
            type={reveal ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={provider === "gemini" ? "AIza…" : "sk-or-…"}
            autoComplete="off"
            spellCheck={false}
            disabled={create.isPending}
            className="font-mono"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={() => setReveal((v) => !v)}
            aria-label={
              reveal
                ? t("settings.integrations.hideKey")
                : t("settings.integrations.showKey")
            }
            disabled={create.isPending}
          >
            {reveal ? (
              <EyeOff className="size-4" />
            ) : (
              <Eye className="size-4" />
            )}
          </Button>
        </div>
        {!keyPrefixOk && (
          <p className="text-destructive text-xs">
            {provider === "gemini"
              ? t("settings.integrations.keyPrefixWarning")
              : t("settings.integrations.orKeyPrefixWarning")}
          </p>
        )}
      </div>
      <div>
        <Button type="submit" disabled={!canSubmit} className="gap-2">
          {create.isPending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Plus className="size-4" aria-hidden />
          )}
          {t("settings.common.add")}
        </Button>
      </div>
    </form>
  );
}
