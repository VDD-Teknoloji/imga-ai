"use client";

// Sprint 13 — /settings/ticket-routing.
//
// Kategori bazlı otomatik atama + e-posta bildirimi kuralları. Kategori
// başına tek kural (backend 409 ile korur); silme soft — is_active=false.
// Alttaki outbox listesi son e-posta bildirimlerini gösterir; SMTP henüz
// yapılandırılmamışsa satırlar pending'de bekler, bilgi notu görünür.

import { Loader2, Mail, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCategories } from "@/hooks/use-categories";
import { useTenantMembers } from "@/hooks/use-tenant-users";
import {
  useCreateTicketRoutingRule,
  useDeleteTicketRoutingRule,
  useTicketRoutingOutbox,
  useTicketRoutingRules,
  useUpdateTicketRoutingRule,
  type OutboxEmailStatus,
  type TicketRoutingRule,
} from "@/hooks/use-ticket-routing";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

export default function TicketRoutingPage() {
  return (
    <RequireRole level="admin">
      <TicketRoutingContent />
    </RequireRole>
  );
}

function TicketRoutingContent() {
  const { t } = useTranslation();
  const rulesQuery = useTicketRoutingRules();
  const categories = useCategories();
  const members = useTenantMembers();

  const rules = rulesQuery.data ?? [];

  const categoryLabelByCode = useMemo(() => {
    const m = new Map<string, string>();
    for (const cat of categories.data ?? []) m.set(cat.code, cat.label_tr);
    return m;
  }, [categories.data]);

  const memberNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const member of members.data?.members ?? [])
      m.set(member.user_id, member.full_name);
    return m;
  }, [members.data]);

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Mail className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("settings.ticketRouting.title")}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t("settings.ticketRouting.subtitle")}
          </p>
        </div>
      </header>

      {rulesQuery.isLoading ? (
        <Skeleton className="h-40" />
      ) : rulesQuery.isError ? (
        <p className="text-destructive text-sm">
          {t("settings.ticketRouting.loadError")}
        </p>
      ) : rules.length === 0 ? (
        <div className="bg-card rounded-lg border border-dashed p-8 text-center">
          <p className="text-muted-foreground text-sm">
            {t("settings.ticketRouting.empty")}
          </p>
        </div>
      ) : (
        <div className="bg-card overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("settings.ticketRouting.colCategory")}</TableHead>
                <TableHead>{t("settings.ticketRouting.colEmail")}</TableHead>
                <TableHead>{t("settings.ticketRouting.colAssignee")}</TableHead>
                <TableHead>{t("settings.ticketRouting.colSla")}</TableHead>
                <TableHead>{t("settings.ticketRouting.colActive")}</TableHead>
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.map((rule) => (
                <RuleRow
                  key={rule.id}
                  rule={rule}
                  categoryLabel={
                    categoryLabelByCode.get(rule.category_code) ??
                    rule.category_code
                  }
                  assigneeName={
                    rule.assignee_user_id
                      ? memberNameById.get(rule.assignee_user_id) ??
                        rule.assignee_user_id
                      : null
                  }
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateRuleForm
        existingCodes={rules.filter((r) => r.is_active).map((r) => r.category_code)}
      />

      <OutboxSection />
    </main>
  );
}

function RuleRow({
  rule,
  categoryLabel,
  assigneeName,
}: {
  rule: TicketRoutingRule;
  categoryLabel: string;
  assigneeName: string | null;
}) {
  const { t } = useTranslation();
  const update = useUpdateTicketRoutingRule();
  const del = useDeleteTicketRoutingRule();

  return (
    <TableRow className={rule.is_active ? "" : "opacity-60"}>
      <TableCell className="font-medium">{categoryLabel}</TableCell>
      <TableCell>{rule.notify_email}</TableCell>
      <TableCell>
        {assigneeName ?? (
          <span className="text-muted-foreground">
            {t("settings.ticketRouting.noAssignee")}
          </span>
        )}
      </TableCell>
      <TableCell>
        {rule.sla_hours !== null
          ? t("settings.ticketRouting.slaHoursValue", { n: rule.sla_hours })
          : "—"}
      </TableCell>
      <TableCell>
        <Switch
          checked={rule.is_active}
          disabled={update.isPending}
          aria-label={t("settings.ticketRouting.activeToggleAria")}
          onCheckedChange={(checked: boolean) =>
            update.mutate(
              { id: rule.id, body: { is_active: checked } },
              {
                onSuccess: () =>
                  toast.success(
                    checked
                      ? t("settings.ticketRouting.ruleEnabled")
                      : t("settings.ticketRouting.ruleDisabled"),
                  ),
                onError: () =>
                  toast.error(t("settings.common.updateFailed")),
              },
            )
          }
        />
      </TableCell>
      <TableCell>
        <Button
          variant="ghost"
          size="sm"
          disabled={del.isPending || !rule.is_active}
          onClick={() =>
            del.mutate(rule.id, {
              onSuccess: () =>
                toast.success(t("settings.ticketRouting.ruleDeleted")),
              onError: () => toast.error(t("settings.common.actionFailed")),
            })
          }
          className="gap-1 text-red-700 hover:text-red-900"
        >
          <Trash2 className="size-3.5" aria-hidden />
          {t("settings.common.delete")}
        </Button>
      </TableCell>
    </TableRow>
  );
}

function CreateRuleForm({ existingCodes }: { existingCodes: string[] }) {
  const { t } = useTranslation();
  const create = useCreateTicketRoutingRule();
  const categories = useCategories();
  const members = useTenantMembers();

  const [categoryCode, setCategoryCode] = useState("");
  const [email, setEmail] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [slaHours, setSlaHours] = useState("");

  const taken = useMemo(() => new Set(existingCodes), [existingCodes]);
  const available = useMemo(
    () =>
      (categories.data ?? []).filter(
        (c) => c.is_enabled && !c.is_archived && !taken.has(c.code),
      ),
    [categories.data, taken],
  );
  const memberList = members.data?.members ?? [];

  function onSubmit() {
    if (!categoryCode) {
      toast.error(t("settings.ticketRouting.categoryRequired"));
      return;
    }
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !trimmedEmail.includes("@")) {
      toast.error(t("settings.ticketRouting.emailInvalid"));
      return;
    }
    const sla = slaHours.trim() === "" ? null : Number(slaHours);
    if (sla !== null && (Number.isNaN(sla) || sla < 1)) {
      toast.error(t("settings.ticketRouting.slaPositive"));
      return;
    }
    create.mutate(
      {
        category_code: categoryCode,
        notify_email: trimmedEmail,
        ...(assigneeId ? { assignee_user_id: assigneeId } : {}),
        ...(sla !== null ? { sla_hours: sla } : {}),
      },
      {
        onSuccess: () => {
          toast.success(t("settings.ticketRouting.ruleAdded"));
          setCategoryCode("");
          setEmail("");
          setAssigneeId("");
          setSlaHours("");
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error(t("settings.ticketRouting.duplicateCategory"));
            return;
          }
          if (err instanceof ApiError) {
            toast.error(err.detail);
            return;
          }
          toast.error(t("settings.ticketRouting.addFailed"));
        },
      },
    );
  }

  return (
    <section className="bg-card space-y-4 rounded-lg border p-4">
      <h2 className="text-base font-semibold">
        {t("settings.ticketRouting.newRule")}
      </h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="routing-category">
            {t("settings.ticketRouting.colCategory")}
          </Label>
          {/* Base UI Select: null = kontrollü boş değer; `|| undefined`
              kontrolsüz moda düşürüp form reset'inde eski seçimi bırakır. */}
          <Select
            value={categoryCode === "" ? null : categoryCode}
            onValueChange={(v: string | null) => setCategoryCode(v ?? "")}
          >
            <SelectTrigger id="routing-category">
              <SelectValue
                placeholder={t("settings.ticketRouting.categoryPlaceholder")}
              />
            </SelectTrigger>
            <SelectContent>
              {available.map((c) => (
                <SelectItem key={c.code} value={c.code}>
                  {c.label_tr}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {available.length === 0 && !categories.isLoading && (
            <p className="text-muted-foreground text-xs">
              {t("settings.ticketRouting.noAvailableCategories")}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="routing-email">
            {t("settings.ticketRouting.colEmail")}
          </Label>
          <Input
            id="routing-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t("settings.ticketRouting.emailPlaceholder")}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="routing-assignee">
            {t("settings.ticketRouting.assigneeOptional")}
          </Label>
          <Select
            value={assigneeId === "" ? null : assigneeId}
            onValueChange={(v: string | null) => setAssigneeId(v ?? "")}
          >
            <SelectTrigger id="routing-assignee">
              <SelectValue
                placeholder={t("settings.ticketRouting.noAssignee")}
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={null}>
                {t("settings.ticketRouting.noAssignee")}
              </SelectItem>
              {memberList.map((m) => (
                <SelectItem key={m.user_id} value={m.user_id}>
                  {m.full_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="routing-sla">
            {t("settings.ticketRouting.slaOptional")}
          </Label>
          <Input
            id="routing-sla"
            type="number"
            min={1}
            value={slaHours}
            onChange={(e) => setSlaHours(e.target.value)}
            placeholder={t("settings.common.optional")}
          />
        </div>
      </div>
      <Button onClick={onSubmit} disabled={create.isPending} className="gap-2">
        {create.isPending ? (
          <Loader2 className="size-4 animate-spin" aria-hidden />
        ) : (
          <Plus className="size-4" aria-hidden />
        )}
        {t("settings.common.add")}
      </Button>
    </section>
  );
}

function OutboxSection() {
  const { t } = useTranslation();
  const outbox = useTicketRoutingOutbox();
  const emails = outbox.data ?? [];

  const pendingCount = emails.filter((e) => e.status === "pending").length;
  const mostlyPending = emails.length > 0 && pendingCount * 2 > emails.length;

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">
        {t("settings.ticketRouting.outboxTitle")}
      </h2>
      {mostlyPending && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          {t("settings.ticketRouting.smtpPendingNote")}
        </p>
      )}
      {outbox.isLoading ? (
        <Skeleton className="h-24" />
      ) : outbox.isError ? (
        <p className="text-destructive text-sm">
          {t("settings.ticketRouting.outboxError")}
        </p>
      ) : emails.length === 0 ? (
        <div className="bg-card rounded-lg border border-dashed p-6 text-center">
          <p className="text-muted-foreground text-sm">
            {t("settings.ticketRouting.outboxEmpty")}
          </p>
        </div>
      ) : (
        <div className="bg-card overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("settings.ticketRouting.outboxDate")}</TableHead>
                <TableHead>
                  {t("settings.ticketRouting.outboxRecipient")}
                </TableHead>
                <TableHead>
                  {t("settings.ticketRouting.outboxSubject")}
                </TableHead>
                <TableHead>
                  {t("settings.ticketRouting.outboxStatus")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {emails.map((email) => (
                <TableRow key={email.id}>
                  <TableCell className="whitespace-nowrap text-xs">
                    {new Date(email.created_at).toLocaleString("tr-TR")}
                  </TableCell>
                  <TableCell className="text-xs">{email.to_email}</TableCell>
                  <TableCell className="text-xs">
                    <span>{email.subject}</span>{" "}
                    <span className="text-muted-foreground">
                      (
                      {email.event_type === "ticket_opened"
                        ? t("settings.ticketRouting.eventTicketOpened")
                        : t("settings.ticketRouting.eventSlaBreach")}
                      )
                    </span>
                  </TableCell>
                  <TableCell>
                    <OutboxStatusBadge
                      status={email.status}
                      lastError={email.last_error}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}

function OutboxStatusBadge({
  status,
  lastError,
}: {
  status: OutboxEmailStatus;
  lastError: string | null;
}) {
  const { t } = useTranslation();
  if (status === "pending")
    return (
      <Badge className="bg-amber-100 text-amber-900 hover:bg-amber-100">
        {t("settings.ticketRouting.statusPending")}
      </Badge>
    );
  if (status === "sent")
    return (
      <Badge className="bg-emerald-100 text-emerald-900 hover:bg-emerald-100">
        {t("settings.ticketRouting.statusSent")}
      </Badge>
    );
  return (
    <Badge
      className="bg-red-100 text-red-900 hover:bg-red-100"
      title={lastError ?? undefined}
    >
      {t("settings.ticketRouting.statusFailed")}
    </Badge>
  );
}
