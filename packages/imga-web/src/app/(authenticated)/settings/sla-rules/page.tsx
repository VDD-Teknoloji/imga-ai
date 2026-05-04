"use client";

// Sprint 8.3.7-A — /settings/sla-rules.
//
// CRUD for tenant SLA rules. URL state Path B (?show_inactive). Each
// rule has match conditions, response/resolution thresholds (at least
// one required), and an action_type. Today the engine only wires
// ``warn_only`` — other action_types are accepted by the API and the
// UI shows "yakında" guidance so tenants can draft for the upcoming
// sprints (8.3.9 ticket creation, 8.6 email notification).

import { Clock, Loader2, Plus, ShieldAlert, Trash2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
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
  useCreateSlaRule,
  useDeleteSlaRule,
  useSlaRules,
  useUpdateSlaRule,
} from "@/hooks/use-sla-rules";
import { useTaxonomies } from "@/hooks/use-taxonomies";
import { ApiError } from "@/lib/api-client";
import {
  SLA_ACTION_AVAILABLE_NOW,
  SLA_ACTION_LABELS,
  type SlaActionType,
  type SlaPriority,
  type SlaRule,
} from "@/lib/types";

const PRIORITY_LABELS: Record<SlaPriority, string> = {
  low: "Düşük",
  normal: "Normal",
  high: "Yüksek",
  urgent: "Acil",
};

export default function SlaRulesPage() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <SlaRulesContent />
    </Suspense>
  );
}

function HeaderSkeleton() {
  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 p-6 md:p-8">
      <header className="flex items-center gap-2">
        <ShieldAlert className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">SLA Kuralları</h1>
          <p className="text-muted-foreground text-sm">Yükleniyor…</p>
        </div>
      </header>
    </main>
  );
}

function SlaRulesContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [showInactive, setShowInactiveState] = useState<boolean>(
    () => searchParams.get("show_inactive") === "true",
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlShow = searchParams.get("show_inactive") === "true";
    setShowInactiveState((prev) => (prev === urlShow ? prev : urlShow));
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParam(key: string, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value === null || value === "") params.delete(key);
    else params.set(key, value);
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const list = useSlaRules({ include_inactive: showInactive });
  const rules = list.data ?? [];

  const [editTarget, setEditTarget] = useState<SlaRule | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 p-6 md:p-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <ShieldAlert className="text-primary mt-1 size-6" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
              SLA Kuralları
            </h1>
            <p className="text-muted-foreground text-sm">
              Belirlenen koşullara uyan analiz veya biletler için
              yanıt/çözüm sürelerini izle. Şu an sadece &quot;Uyarı&quot;
              aksiyonu aktif; bilet oluşturma ve e-posta bildirimi
              ileriki sprint&apos;lerde devreye girecek.
            </p>
          </div>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="size-4" aria-hidden /> Kural ekle
        </Button>
      </header>

      <div className="bg-card flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => {
              setShowInactiveState(e.target.checked);
              pushParam("show_inactive", e.target.checked ? "true" : null);
            }}
            className="size-4"
          />
          Devre dışı kuralları göster
        </label>
        <span className="text-muted-foreground ml-auto text-xs">
          {rules.length} kural
        </span>
      </div>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      ) : list.isError ? (
        <p className="text-destructive p-6 text-sm">Kurallar yüklenemedi.</p>
      ) : rules.length === 0 ? (
        <div className="bg-card rounded-lg border border-dashed p-8 text-center">
          <p className="text-muted-foreground text-sm">
            Henüz SLA kuralı yok. &quot;Kural ekle&quot; ile ilkini
            tanımlayın.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {rules.map((rule) => (
            <SlaRuleRow
              key={rule.id}
              rule={rule}
              onEdit={() => setEditTarget(rule)}
            />
          ))}
        </ul>
      )}

      <CreateModal open={createOpen} onClose={() => setCreateOpen(false)} />
      {editTarget && (
        <EditModal target={editTarget} onClose={() => setEditTarget(null)} />
      )}
    </main>
  );
}

function SlaRuleRow({
  rule,
  onEdit,
}: {
  rule: SlaRule;
  onEdit: () => void;
}) {
  const del = useDeleteSlaRule();
  const summary = formatConditions(rule);
  const thresholds = formatThresholds(rule);
  return (
    <li
      className={`bg-card flex items-start justify-between gap-3 rounded-lg border p-3 ${
        rule.is_active ? "" : "opacity-60"
      }`}
    >
      <div className="flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onEdit}
            className="text-sm font-medium hover:underline"
          >
            {rule.name}
          </button>
          <Badge variant="outline" className="text-xs">
            {SLA_ACTION_LABELS[rule.action_type]}
          </Badge>
          {!SLA_ACTION_AVAILABLE_NOW.has(rule.action_type) && (
            <span className="text-muted-foreground text-xs">
              (bu aksiyon henüz aktif değil)
            </span>
          )}
          {!rule.is_active && (
            <Badge
              variant="outline"
              className="border-zinc-300 bg-zinc-50 text-xs text-zinc-700"
            >
              Devre dışı
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground text-xs">
          Koşul: {summary || "tüm analizler"}
        </p>
        <p className="text-muted-foreground text-xs">
          <Clock className="mr-1 inline size-3" aria-hidden />
          Eşik: {thresholds}
        </p>
      </div>
      <div className="flex flex-col items-end gap-2">
        <Button variant="ghost" size="sm" onClick={onEdit}>
          Düzenle
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={del.isPending || !rule.is_active}
          onClick={() =>
            del.mutate(rule.id, {
              onSuccess: () => toast.success("Kural devre dışı bırakıldı."),
              onError: () => toast.error("İşlem başarısız."),
            })
          }
          className="gap-1 text-red-700 hover:text-red-900"
        >
          <Trash2 className="size-3.5" aria-hidden /> Sil
        </Button>
      </div>
    </li>
  );
}

function formatConditions(rule: SlaRule): string {
  const parts: string[] = [];
  if (rule.match_priority) {
    parts.push(`öncelik=${PRIORITY_LABELS[rule.match_priority]}`);
  }
  if (rule.match_taxonomy_codes?.length) {
    parts.push(`kategori=${rule.match_taxonomy_codes.length} kod`);
  }
  if (rule.match_company_perspective_codes?.length) {
    parts.push(
      `perspektif=${rule.match_company_perspective_codes.length} kod`,
    );
  }
  if (rule.match_nps_score_max !== null) {
    parts.push(`NPS≤${rule.match_nps_score_max}`);
  }
  return parts.join(" · ");
}

function formatThresholds(rule: SlaRule): string {
  const out: string[] = [];
  if (rule.response_sla_minutes !== null) {
    out.push(`yanıt ${formatMinutes(rule.response_sla_minutes)}`);
  }
  if (rule.resolution_sla_minutes !== null) {
    out.push(`çözüm ${formatMinutes(rule.resolution_sla_minutes)}`);
  }
  return out.join(" · ");
}

function formatMinutes(m: number): string {
  if (m < 60) return `${m}dk`;
  if (m < 60 * 24) {
    const h = Math.floor(m / 60);
    const rem = m % 60;
    return rem === 0 ? `${h}sa` : `${h}sa${rem}dk`;
  }
  const days = Math.floor(m / (60 * 24));
  const remH = Math.floor((m % (60 * 24)) / 60);
  return remH === 0 ? `${days}g` : `${days}g${remH}sa`;
}

// --- Create + Edit modals ----------------------------------------------

interface RuleFormState {
  name: string;
  match_priority: SlaPriority | "";
  match_taxonomy_codes: string;
  match_nps_score_max: string;
  response_sla_minutes: string;
  resolution_sla_minutes: string;
  action_type: SlaActionType;
  is_active: boolean;
}

function emptyForm(): RuleFormState {
  return {
    name: "",
    match_priority: "",
    match_taxonomy_codes: "",
    match_nps_score_max: "",
    response_sla_minutes: "",
    resolution_sla_minutes: "",
    action_type: "warn_only",
    is_active: true,
  };
}

function fromRule(rule: SlaRule): RuleFormState {
  return {
    name: rule.name,
    match_priority: rule.match_priority ?? "",
    match_taxonomy_codes: (rule.match_taxonomy_codes ?? []).join(","),
    match_nps_score_max:
      rule.match_nps_score_max === null
        ? ""
        : String(rule.match_nps_score_max),
    response_sla_minutes:
      rule.response_sla_minutes === null
        ? ""
        : String(rule.response_sla_minutes),
    resolution_sla_minutes:
      rule.resolution_sla_minutes === null
        ? ""
        : String(rule.resolution_sla_minutes),
    action_type: rule.action_type,
    is_active: rule.is_active,
  };
}

function buildPayload(form: RuleFormState): {
  ok: boolean;
  reason?: string;
  payload?: {
    name: string;
    match_priority: SlaPriority | null;
    match_taxonomy_codes: string[] | null;
    match_nps_score_max: number | null;
    response_sla_minutes: number | null;
    resolution_sla_minutes: number | null;
    action_type: SlaActionType;
    is_active: boolean;
  };
} {
  const name = form.name.trim();
  if (!name) return { ok: false, reason: "İsim boş olamaz." };

  const respMin = form.response_sla_minutes
    ? Number(form.response_sla_minutes)
    : null;
  const resMin = form.resolution_sla_minutes
    ? Number(form.resolution_sla_minutes)
    : null;
  if (respMin === null && resMin === null) {
    return {
      ok: false,
      reason: "Yanıt veya çözüm süresinden en az birini girin.",
    };
  }
  if (respMin !== null && (Number.isNaN(respMin) || respMin < 1)) {
    return { ok: false, reason: "Yanıt süresi pozitif bir sayı olmalı." };
  }
  if (resMin !== null && (Number.isNaN(resMin) || resMin < 1)) {
    return { ok: false, reason: "Çözüm süresi pozitif bir sayı olmalı." };
  }

  const npsRaw = form.match_nps_score_max.trim();
  const nps = npsRaw === "" ? null : Number(npsRaw);
  if (nps !== null && (Number.isNaN(nps) || nps < 0 || nps > 10)) {
    return { ok: false, reason: "NPS eşiği 0 ile 10 arası olmalı." };
  }

  const codes = form.match_taxonomy_codes
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);

  return {
    ok: true,
    payload: {
      name,
      match_priority: form.match_priority || null,
      match_taxonomy_codes: codes.length > 0 ? codes : null,
      match_nps_score_max: nps,
      response_sla_minutes: respMin,
      resolution_sla_minutes: resMin,
      action_type: form.action_type,
      is_active: form.is_active,
    },
  };
}

function CreateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreateSlaRule();
  const taxonomies = useTaxonomies();
  const [form, setForm] = useState<RuleFormState>(emptyForm());

  // Reset the form when the dialog opens. Same form-mirror pattern
  // as /settings/profile + /settings/integrations — TanStack Query
  // is the external system; the form fields are React state; we sync
  // when the modal toggles.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (open) setForm(emptyForm());
  }, [open]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function onSubmit() {
    const result = buildPayload(form);
    if (!result.ok) {
      toast.error(result.reason ?? "Form geçersiz.");
      return;
    }
    create.mutate(result.payload!, {
      onSuccess: () => {
        toast.success("Kural eklendi.");
        onClose();
      },
      onError: (err) => {
        if (err instanceof ApiError) {
          toast.error(err.detail);
          return;
        }
        toast.error("Kural eklenemedi.");
      },
    });
  }

  return (
    <Dialog open={open} onOpenChange={(v) => (v ? null : onClose())}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Yeni SLA Kuralı</DialogTitle>
          <DialogDescription>
            Yanıt veya çözüm sürelerinden en az biri zorunludur.
          </DialogDescription>
        </DialogHeader>
        <RuleFormFields
          form={form}
          setForm={setForm}
          taxonomyCodes={
            (taxonomies.data ?? []).filter((t) => t.is_active).map((t) => t.code)
          }
        />
        <DialogFooter>
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
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditModal({
  target,
  onClose,
}: {
  target: SlaRule;
  onClose: () => void;
}) {
  const update = useUpdateSlaRule();
  const taxonomies = useTaxonomies();
  const [form, setForm] = useState<RuleFormState>(() => fromRule(target));

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setForm(fromRule(target));
  }, [target]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function onSubmit() {
    const result = buildPayload(form);
    if (!result.ok) {
      toast.error(result.reason ?? "Form geçersiz.");
      return;
    }
    update.mutate(
      { id: target.id, body: result.payload! },
      {
        onSuccess: () => {
          toast.success("Kural güncellendi.");
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            toast.error(err.detail);
            return;
          }
          toast.error("Güncelleme başarısız.");
        },
      },
    );
  }

  return (
    <Dialog open onOpenChange={(v) => (v ? null : onClose())}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{target.name}</DialogTitle>
          <DialogDescription>SLA kuralını düzenle.</DialogDescription>
        </DialogHeader>
        <RuleFormFields
          form={form}
          setForm={setForm}
          taxonomyCodes={
            (taxonomies.data ?? []).filter((t) => t.is_active).map((t) => t.code)
          }
        />
        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={update.isPending}
          >
            İptal
          </Button>
          <Button
            onClick={onSubmit}
            disabled={update.isPending}
            className="gap-2"
          >
            {update.isPending && <Loader2 className="size-4 animate-spin" />}
            Kaydet
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RuleFormFields({
  form,
  setForm,
  taxonomyCodes,
}: {
  form: RuleFormState;
  setForm: (next: RuleFormState) => void;
  taxonomyCodes: string[];
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="rule-name">İsim</Label>
        <Input
          id="rule-name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          maxLength={128}
          placeholder="Örn. Acil bilet — kritik yanıt SLA"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="rule-priority">Öncelik (eşleşme)</Label>
          <Select
            value={form.match_priority || undefined}
            onValueChange={(v) =>
              setForm({
                ...form,
                match_priority: ((v ?? "") as SlaPriority | "") || "",
              })
            }
          >
            <SelectTrigger id="rule-priority">
              <SelectValue placeholder="(tümü)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">(tümü)</SelectItem>
              {(["low", "normal", "high", "urgent"] as SlaPriority[]).map(
                (p) => (
                  <SelectItem key={p} value={p}>
                    {PRIORITY_LABELS[p]}
                  </SelectItem>
                ),
              )}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="rule-nps">NPS eşiği (en fazla)</Label>
          <Input
            id="rule-nps"
            type="number"
            min={0}
            max={10}
            value={form.match_nps_score_max}
            onChange={(e) =>
              setForm({ ...form, match_nps_score_max: e.target.value })
            }
            placeholder="(opsiyonel)"
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="rule-codes">Kategori kodları (virgülle)</Label>
        <Input
          id="rule-codes"
          value={form.match_taxonomy_codes}
          onChange={(e) =>
            setForm({ ...form, match_taxonomy_codes: e.target.value })
          }
          placeholder="shipment_not_arrived, broken_damaged"
        />
        {taxonomyCodes.length > 0 && (
          <p className="text-muted-foreground text-xs">
            Geçerli kodlar: {taxonomyCodes.slice(0, 5).join(", ")}
            {taxonomyCodes.length > 5 && ` +${taxonomyCodes.length - 5} daha`}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="rule-response">Yanıt süresi (dakika)</Label>
          <Input
            id="rule-response"
            type="number"
            min={1}
            value={form.response_sla_minutes}
            onChange={(e) =>
              setForm({ ...form, response_sla_minutes: e.target.value })
            }
            placeholder="(opsiyonel)"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="rule-resolution">Çözüm süresi (dakika)</Label>
          <Input
            id="rule-resolution"
            type="number"
            min={1}
            value={form.resolution_sla_minutes}
            onChange={(e) =>
              setForm({ ...form, resolution_sla_minutes: e.target.value })
            }
            placeholder="(opsiyonel)"
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="rule-action">Aksiyon</Label>
        <Select
          value={form.action_type}
          onValueChange={(v) =>
            setForm({
              ...form,
              action_type: ((v ?? "warn_only") as SlaActionType),
            })
          }
        >
          <SelectTrigger id="rule-action">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(SLA_ACTION_LABELS) as SlaActionType[]).map((a) => (
              <SelectItem key={a} value={a}>
                {SLA_ACTION_LABELS[a]}
                {!SLA_ACTION_AVAILABLE_NOW.has(a) && " (yakında)"}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {!SLA_ACTION_AVAILABLE_NOW.has(form.action_type) && (
          <p className="text-muted-foreground text-xs">
            Bu aksiyon ileriki sprint&apos;te aktive olacak; şimdiden
            kuralı tanımlayabilirsiniz.
          </p>
        )}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.is_active}
          onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
          className="size-4"
        />
        Etkin
      </label>
    </div>
  );
}
