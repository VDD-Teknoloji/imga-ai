"use client";

// 2026-08-09 — /admin/tenants/{id}/llm.
//
// Yapay zekâ modeli + API anahtarı yönetimi kurumdan alınıp süper
// yöneticiye verildi. Bu sayfa eski /settings/integrations CRUD'unun
// yeni evi: sağlayıcı + model seçimi, anahtar ekleme, aktiflik,
// silme ve sürükle-bırak öncelik sıralaması — hepsi tek bir kurum
// için.
//
// Güvenlik UX'i: düz metin yalnız Ekle formunun içinde yaşar. Yanıt
// sadece son-4 önizlemesini taşır; form gönderimden sonra alanı
// temizler, böylece sayfa sırrı bir daha render etmez.

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
  ChevronLeft,
  ChevronsUpDown,
  Cpu,
  Eye,
  EyeOff,
  GripVertical,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

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
  useAdminLlmCredentials,
  useAdminOpenRouterModels,
  useCreateAdminLlmCredential,
  useDeleteAdminLlmCredential,
  useReorderAdminLlmCredentials,
  useUpdateAdminLlmCredential,
} from "@/hooks/use-admin-llm-credentials";
import { useAdminTenants } from "@/hooks/use-admin-tenants";
import { ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { LlmCredential, LlmProviderName } from "@/lib/types";
import { cn } from "@/lib/utils";

const GEMINI_KEY_PREFIX = "AIza";
const OPENROUTER_KEY_PREFIX = "sk-or-";

const PROVIDER_BADGE: Record<string, string> = {
  gemini: "Gemini",
  openrouter: "OpenRouter",
};

/** Aranabilir OpenRouter model seçicisi — hem Ekle formu hem satır içi
 *  değişiklik aynı bileşeni kullanır. Katalog süper-yönetici ucundan
 *  gelir; yeni model çıktığında kod değişikliği gerekmez. */
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
  const catalog = useAdminOpenRouterModels(open);
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
              {value ?? t("admin.llm.modelDefault")}
            </span>
            <ChevronsUpDown className="size-3.5 shrink-0 opacity-60" aria-hidden />
          </Button>
        }
      />
      <PopoverContent align="start" className="w-[340px] p-0">
        <Command>
          <CommandInput placeholder={t("admin.llm.modelSearchPlaceholder")} />
          <CommandList className="max-h-[320px]">
            <CommandEmpty>
              {catalog.isLoading
                ? t("common.loading")
                : t("admin.llm.modelEmpty")}
            </CommandEmpty>
            <CommandGroup>
              <CommandItem
                value="__default__ varsayilan default"
                onSelect={() => pick(null)}
                className="flex items-center justify-between gap-2"
              >
                <span>{t("admin.llm.modelDefault")}</span>
                {value === null && (
                  <Check className="text-primary size-4" aria-hidden />
                )}
              </CommandItem>
            </CommandGroup>
            {recommended.length > 0 && (
              <CommandGroup heading={t("admin.llm.modelRecommended")}>
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
              <CommandGroup heading={t("admin.llm.modelAll")}>
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

/**
 * Süper-yönetici LLM sayfası. Sidebar zaten kurum yönetimini
 * `is_super_admin` ile kapatıyor ama URL doğrudan da açılabildiği için
 * sayfa kendini de korur — aksi halde kullanıcı 403'e çarpar.
 */
export default function AdminTenantLlmPage() {
  const isSuperAdmin = useAuthStore((s) => s.user?.is_super_admin ?? false);
  if (!isSuperAdmin) {
    return <ForbiddenView />;
  }
  return <AdminTenantLlmBody />;
}

function ForbiddenView() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-3xl p-6 md:p-8">
      <div className="bg-card space-y-2 rounded-lg border p-8 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("admin.tenants.forbidden.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("admin.tenants.forbidden.desc")}
        </p>
      </div>
    </main>
  );
}

function AdminTenantLlmBody() {
  const { t } = useTranslation();
  const params = useParams<{ id: string }>();
  const tenantId = params.id;

  const tenants = useAdminTenants();
  const tenant = (tenants.data ?? []).find((row) => row.id === tenantId);
  const list = useAdminLlmCredentials(tenantId);
  const credentials = list.data ?? [];

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 p-6 md:p-8">
      <Link
        href="/admin/tenants"
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ChevronLeft className="size-4" aria-hidden />
        {t("admin.llm.backToTenants")}
      </Link>

      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight md:text-3xl">
          <Cpu className="text-primary size-5 md:size-6" aria-hidden />
          {t("admin.llm.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {tenant
            ? t("admin.llm.subtitleFor", { tenant: tenant.name })
            : t("admin.llm.subtitle")}
        </p>
      </header>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : list.isError ? (
        <p className="text-destructive p-6 text-sm">
          {t("admin.llm.loadError")}
        </p>
      ) : credentials.length === 0 ? (
        <EmptyState />
      ) : (
        <KeyList tenantId={tenantId} credentials={credentials} />
      )}

      <AddKeyForm tenantId={tenantId} />
    </main>
  );
}

function EmptyState() {
  const { t } = useTranslation();
  return (
    <div className="bg-card rounded-lg border border-dashed p-8 text-center">
      <p className="text-muted-foreground text-sm">{t("admin.llm.empty")}</p>
    </div>
  );
}

function KeyList({
  tenantId,
  credentials,
}: {
  tenantId: string;
  credentials: LlmCredential[];
}) {
  const reorder = useReorderAdminLlmCredentials(tenantId);
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
          toast.error(t("admin.llm.reorderFailed"));
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
            <SortableKeyRow
              key={cred.id}
              tenantId={tenantId}
              credential={cred}
              index={idx}
            />
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}

function SortableKeyRow({
  tenantId,
  credential,
  index,
}: {
  tenantId: string;
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
        aria-label={t("admin.llm.dragHandle")}
      >
        <GripVertical className="size-5" aria-hidden />
      </button>
      <KeyRow tenantId={tenantId} credential={credential} index={index} />
    </li>
  );
}

function KeyRow({
  tenantId,
  credential,
  index,
}: {
  tenantId: string;
  credential: LlmCredential;
  index: number;
}) {
  const update = useUpdateAdminLlmCredential(tenantId);
  const del = useDeleteAdminLlmCredential(tenantId);
  const { t } = useTranslation();
  const [label, setLabel] = useState(credential.label);
  const [editing, setEditing] = useState(false);

  // Sıralama + refetch, satır monteliyken alttaki kaydı değiştirebilir;
  // düzenlenebilir kopyayı sunucu değerine geri senkronla. /settings
  // sayfalarındaki form-mirror kalıbının aynısı.
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
            toast.error(t("admin.llm.labelUpdateFailed"));
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
              title={t("admin.llm.editLabel")}
            >
              {credential.label}
            </button>
          )}
          <Badge variant="outline" className="text-xs">
            {index === 0
              ? t("admin.llm.primary")
              : t("admin.llm.backup", { n: index })}
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
              title={t("admin.llm.lastFailed", {
                date: new Date(credential.last_failed_at).toLocaleString("tr-TR"),
              })}
            >
              <AlertTriangle className="mr-1 size-3" aria-hidden />
              {t("admin.llm.warning")}
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
                  { id: credential.id, body: { model } },
                  {
                    onSuccess: () => toast.success(t("admin.llm.modelChanged")),
                    onError: () =>
                      toast.error(t("admin.llm.modelChangeFailed")),
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
              onError: () => toast.error(t("admin.llm.statusUpdateFailed")),
            },
          )
        }
        aria-label={t("admin.llm.toggleActive")}
      />
      <DeleteKeyButton
        label={credential.label}
        pending={del.isPending}
        onConfirm={() =>
          del.mutate(credential.id, {
            onSuccess: () => toast.success(t("admin.llm.keyDeleted")),
            onError: () => toast.error(t("admin.llm.deleteFailed")),
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
            aria-label={t("admin.llm.deleteAria", { label })}
          >
            <Trash2 className="size-4" />
          </Button>
        }
      />
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t("admin.llm.deleteConfirmTitle")}
          </AlertDialogTitle>
          <AlertDialogDescription>
            <span className="font-medium">{label}</span>{" "}
            {t("admin.llm.deleteConfirmDesc")}
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
            {t("admin.llm.delete")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function AddKeyForm({ tenantId }: { tenantId: string }) {
  const create = useCreateAdminLlmCredential(tenantId);
  const { t } = useTranslation();
  // Yeni eklemelerde varsayılan OpenRouter (ürün kararı — "Gemini
  // yerine OpenRouter"): mevcut Gemini kayıtları çalışmaya devam eder.
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
          // Düz metni hemen temizle — ekran paylaşımı ya da yukarı
          // kaydırma anahtarı bir daha görmesin.
          setLabel("");
          setApiKey("");
          setModel(null);
          setReveal(false);
          toast.success(t("admin.llm.keyAdded"));
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400) {
            toast.error(err.detail);
            return;
          }
          toast.error(t("admin.llm.addFailed"));
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="bg-card space-y-3 rounded-lg border p-4">
      <h2 className="text-base font-semibold">{t("admin.llm.addTitle")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="key-provider">{t("admin.llm.providerField")}</Label>
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
            <Label>{t("admin.llm.modelField")}</Label>
            <ModelPicker
              value={model}
              onSelect={setModel}
              disabled={create.isPending}
            />
          </div>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="key-label">{t("admin.llm.labelField")}</Label>
        <Input
          id="key-label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={t("admin.llm.labelPlaceholder")}
          maxLength={64}
          disabled={create.isPending}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="key-value">{t("admin.llm.apiKeyField")}</Label>
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
              reveal ? t("admin.llm.hideKey") : t("admin.llm.showKey")
            }
            disabled={create.isPending}
          >
            {reveal ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </Button>
        </div>
        {!keyPrefixOk && (
          <p className="text-destructive text-xs">
            {provider === "gemini"
              ? t("admin.llm.keyPrefixWarning")
              : t("admin.llm.orKeyPrefixWarning")}
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
          {t("admin.llm.add")}
        </Button>
      </div>
    </form>
  );
}
