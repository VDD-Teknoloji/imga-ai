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
  Eye,
  EyeOff,
  GripVertical,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  useCreateLlmCredential,
  useDeleteLlmCredential,
  useLlmCredentials,
  useReorderLlmCredentials,
  useUpdateLlmCredential,
} from "@/hooks/use-llm-credentials";
import { ApiError } from "@/lib/api-client";
import type { LlmCredential } from "@/lib/types";

const GEMINI_KEY_PREFIX = "AIza";

export default function IntegrationsPage() {
  const list = useLlmCredentials();
  const credentials = list.data ?? [];

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          Gemini API Anahtarları
        </h1>
        <p className="text-muted-foreground text-sm">
          Strateji raporları için Gemini API anahtarlarınızı buradan
          yönetirsiniz. İlk anahtar birincil; sonrakiler birincil
          başarısız olduğunda sırayla denenir. Anahtarın tamamı asla
          ekranda gösterilmez — yalnızca son 4 karakter önizlemesi.
        </p>
      </header>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      ) : list.isError ? (
        <p className="text-destructive p-6 text-sm">
          Anahtarlar yüklenemedi.
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
  return (
    <div className="bg-card rounded-lg border border-dashed p-8 text-center">
      <p className="text-muted-foreground text-sm">
        Henüz API anahtarı eklenmemiş. Aşağıdaki formdan ilk
        anahtarınızı ekleyin.
      </p>
    </div>
  );
}

function KeyList({ credentials }: { credentials: LlmCredential[] }) {
  const reorder = useReorderLlmCredentials();
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
          toast.error("Sıralama kaydedilemedi.");
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

function priorityLabel(index: number): string {
  return index === 0 ? "Birincil" : `Yedek ${index}`;
}

function SortableKeyRow({
  credential,
  index,
}: {
  credential: LlmCredential;
  index: number;
}) {
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
        aria-label="Sıralama tutamağı"
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
            toast.error("Etiket güncellenemedi.");
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
              title="Etiketi düzenle"
            >
              {credential.label}
            </button>
          )}
          <Badge variant="outline" className="text-xs">
            {priorityLabel(index)}
          </Badge>
          {credential.last_failed_at && (
            <Badge
              variant="outline"
              className="border-amber-400 bg-amber-50 text-xs text-amber-700"
              title={`Son başarısız: ${new Date(
                credential.last_failed_at,
              ).toLocaleString("tr-TR")}`}
            >
              <AlertTriangle className="mr-1 size-3" aria-hidden />
              dikkat
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground font-mono text-xs">
          {credential.value_preview}
        </p>
      </div>
      <Switch
        checked={credential.is_active}
        onCheckedChange={(checked) =>
          update.mutate(
            { id: credential.id, body: { is_active: checked } },
            {
              onError: () => toast.error("Durum güncellenemedi."),
            },
          )
        }
        aria-label="Etkinleştir/Devre dışı"
      />
      <DeleteKeyButton
        label={credential.label}
        pending={del.isPending}
        onConfirm={() =>
          del.mutate(credential.id, {
            onSuccess: () => toast.success("Anahtar silindi."),
            onError: () => toast.error("Silme başarısız."),
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
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            disabled={pending}
            aria-label={`${label} sil`}
          >
            <Trash2 className="size-4" />
          </Button>
        }
      />
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>API anahtarı silinsin mi?</AlertDialogTitle>
          <AlertDialogDescription>
            <span className="font-medium">{label}</span> anahtarı kalıcı
            olarak silinecek. Bu işlem geri alınamaz; anahtar Gemini
            tarafında geçerli kalmaya devam eder, isterseniz tekrar
            ekleyebilirsiniz.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>İptal</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              onConfirm();
              setOpen(false);
            }}
          >
            Sil
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function AddKeyForm() {
  const create = useCreateLlmCredential();
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [reveal, setReveal] = useState(false);

  const trimmed = apiKey.trim();
  const looksLikeGeminiKey =
    trimmed.length === 0 || trimmed.startsWith(GEMINI_KEY_PREFIX);
  const canSubmit =
    !create.isPending &&
    label.trim().length > 0 &&
    trimmed.length >= 10 &&
    looksLikeGeminiKey;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    create.mutate(
      { label: label.trim(), api_key: trimmed },
      {
        onSuccess: () => {
          // Clear plaintext immediately so a screenshare or scroll-up
          // can't surface the key.
          setLabel("");
          setApiKey("");
          setReveal(false);
          toast.success("Anahtar eklendi.");
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400) {
            toast.error(err.detail);
            return;
          }
          toast.error("Anahtar eklenemedi.");
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="bg-card space-y-3 rounded-lg border p-4">
      <h2 className="text-base font-semibold">Yeni anahtar ekle</h2>
      <div className="space-y-2">
        <Label htmlFor="key-label">Etiket</Label>
        <Input
          id="key-label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Örn. Birincil Hesap"
          maxLength={64}
          disabled={create.isPending}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="key-value">API anahtarı</Label>
        <div className="flex gap-2">
          <Input
            id="key-value"
            type={reveal ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="AIza…"
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
            aria-label={reveal ? "Anahtarı gizle" : "Anahtarı göster"}
            disabled={create.isPending}
          >
            {reveal ? (
              <EyeOff className="size-4" />
            ) : (
              <Eye className="size-4" />
            )}
          </Button>
        </div>
        {!looksLikeGeminiKey && (
          <p className="text-destructive text-xs">
            Gemini anahtarları &quot;AIza&quot; ile başlar.
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
          Ekle
        </Button>
      </div>
    </form>
  );
}
