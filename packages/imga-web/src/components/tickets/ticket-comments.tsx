"use client";

import { Archive } from "lucide-react";
import { useMemo, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useArchiveComment,
  useCreateComment,
  useTicketComments,
} from "@/hooks/use-comments";
import { useTenantMembers } from "@/hooks/use-tenant-members";
import { useAuthStore } from "@/lib/auth-store";
import { formatRelativeDate } from "@/lib/date-format";
import { useTranslation } from "@/lib/i18n/use-translation";
import type {
  TenantMember,
  TicketComment,
  TicketCommentKind,
  TicketState,
} from "@/lib/types";
import { COMMENT_KIND_LABELS, userInitials } from "@/lib/user-helpers";
import { cn } from "@/lib/utils";

interface TicketCommentsProps {
  ticketId: string;
  ticketState: TicketState;
}

/**
 * Yorumlar bölümü — ticket detayının altında. Sprint 7.5.5 / Alt-Faz 4
 * arka uç:
 *
 *   * VIEWER → yalnızca ``internal_note`` yazabilir; ``customer_reply``
 *     radio'sunu hiç görmez.
 *   * ANALYST + TENANT_ADMIN → her iki tipi de yazabilir.
 *   * Ticket CLOSED veya CANCELLED iken ``customer_reply`` disable
 *     (tooltip ile sebep gösterilir); ``internal_note`` hâlâ yazılabilir.
 *   * Arşivleme: yazar veya tenant_admin. Soft delete; satır timeline'da
 *     ``is_archived=true`` ile görünmeye devam eder.
 *
 * Düzenleme (5dk pencere) henüz yok — backend'de PATCH endpoint'i
 * yok; Sprint 7.7.2 raporunda eksik olarak işaretlendi.
 */
export function TicketComments({ ticketId, ticketState }: TicketCommentsProps) {
  const { t } = useTranslation();
  const comments = useTicketComments(ticketId);
  const currentUserId = useAuthStore((s) => s.user?.id);
  const role = useAuthStore((s) => s.activeContext?.role);
  const activeTenantId = useAuthStore((s) => s.activeContext?.tenant_id);
  const members = useTenantMembers(activeTenantId);

  const memberMap = useMemo<ReadonlyMap<string, TenantMember>>(() => {
    const map = new Map<string, TenantMember>();
    for (const m of members.data ?? []) {
      map.set(m.user_id, m);
    }
    return map;
  }, [members.data]);

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold tracking-tight">
        {t("tickets.comments.title")}
        {comments.data ? (
          <span className="text-muted-foreground ml-2 text-sm font-normal">
            ({comments.data.length})
          </span>
        ) : null}
      </h2>

      {comments.isLoading ? (
        <div className="space-y-2">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : comments.isError ? (
        <p className="text-destructive text-sm">{t("tickets.comments.loadError")}</p>
      ) : comments.data && comments.data.length > 0 ? (
        <ul className="space-y-3">
          {comments.data.map((c) => (
            <CommentCard
              key={c.id}
              comment={c}
              ticketId={ticketId}
              author={c.author_user_id ? memberMap.get(c.author_user_id) : undefined}
              currentUserId={currentUserId}
              isAdmin={role === "tenant_admin"}
            />
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground text-sm">{t("tickets.comments.empty")}</p>
      )}

      <CommentComposer
        ticketId={ticketId}
        ticketState={ticketState}
        role={role ?? null}
      />
    </section>
  );
}

// --- list item -----------------------------------------------------------

interface CommentCardProps {
  comment: TicketComment;
  ticketId: string;
  author: TenantMember | undefined;
  currentUserId: string | undefined;
  isAdmin: boolean;
}

function CommentCard({
  comment,
  ticketId,
  author,
  currentUserId,
  isAdmin,
}: CommentCardProps) {
  const { t } = useTranslation();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const archive = useArchiveComment();

  const canArchive =
    !comment.is_archived &&
    (isAdmin ||
      (currentUserId !== undefined &&
        comment.author_user_id === currentUserId));

  const displayName = author?.full_name ?? t("tickets.common.unknownUser");
  const isCustomerReply = comment.kind === "customer_reply";

  function handleConfirmArchive() {
    archive.mutate(
      { ticketId, commentId: comment.id },
      { onSuccess: () => setConfirmOpen(false) },
    );
  }

  return (
    <li
      className={cn(
        "bg-card flex gap-3 rounded-md border p-3",
        comment.is_archived && "opacity-60",
        isCustomerReply && !comment.is_archived && "border-primary/40",
      )}
    >
      <Avatar size="sm">
        <AvatarFallback>
          {userInitials({
            full_name: author?.full_name,
            email: author?.email,
          })}
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">{displayName}</span>
          <Badge
            variant={isCustomerReply ? "default" : "secondary"}
            className="h-5 px-1.5 text-xs"
          >
            {COMMENT_KIND_LABELS[comment.kind]}
          </Badge>
          {comment.is_archived ? (
            <Badge variant="outline" className="h-5 px-1.5 text-xs">
              {t("tickets.common.archived")}
            </Badge>
          ) : null}
          <span className="text-muted-foreground ml-auto text-xs">
            {formatRelativeDate(comment.created_at)}
          </span>
        </div>
        <p
          className={cn(
            "text-foreground text-sm whitespace-pre-wrap break-words",
            comment.is_archived && "line-through",
          )}
        >
          {comment.body}
        </p>
        {canArchive ? (
          <div className="flex justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmOpen(true)}
              className="h-7 gap-1.5 text-xs"
            >
              <Archive className="size-3" aria-hidden />
              {t("tickets.comments.archive")}
            </Button>
          </div>
        ) : null}
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("tickets.comments.archiveTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("tickets.comments.archiveDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={archive.isPending}>
              {t("tickets.common.dismiss")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmArchive}
              disabled={archive.isPending}
            >
              {archive.isPending
                ? t("tickets.comments.archiving")
                : t("tickets.comments.archive")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
}

// --- composer ------------------------------------------------------------

interface CommentComposerProps {
  ticketId: string;
  ticketState: TicketState;
  role: "tenant_admin" | "analyst" | "viewer" | null;
}

function CommentComposer({
  ticketId,
  ticketState,
  role,
}: CommentComposerProps) {
  const { t } = useTranslation();
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<TicketCommentKind>("internal_note");
  const create = useCreateComment();

  const isViewer = role === "viewer";
  const isTerminal = ticketState === "closed" || ticketState === "cancelled";
  const customerReplyDisabled = isViewer || isTerminal;

  // React 19 set-state-in-effect rule: snap kind back to internal_note
  // if the disable conditions kick in mid-session (e.g. ticket got
  // closed in another tab). This is a render-time conditional setState,
  // which React bails out of correctly without a cascading re-render.
  const [lastDisabledFlag, setLastDisabledFlag] = useState(customerReplyDisabled);
  if (lastDisabledFlag !== customerReplyDisabled) {
    setLastDisabledFlag(customerReplyDisabled);
    if (customerReplyDisabled && kind === "customer_reply") {
      setKind("internal_note");
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = body.trim();
    if (trimmed.length === 0) return;
    create.mutate(
      { ticketId, body: trimmed, kind },
      {
        onSuccess: () => {
          setBody("");
          setKind("internal_note");
        },
      },
    );
  }

  const submitDisabled = body.trim().length === 0 || create.isPending;

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-card space-y-3 rounded-md border p-3"
    >
      <Textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder={t("tickets.comments.placeholder")}
        maxLength={8000}
        rows={3}
        aria-label={t("tickets.comments.ariaBody")}
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <KindToggle
          kind={kind}
          onChange={setKind}
          showCustomerReply={!isViewer}
          customerReplyDisabled={customerReplyDisabled}
          isTerminal={isTerminal}
        />
        <Button type="submit" disabled={submitDisabled}>
          {create.isPending ? t("tickets.comments.sending") : t("tickets.comments.send")}
        </Button>
      </div>
      {create.isError ? (
        <p className="text-destructive text-xs">
          {t("tickets.comments.sendError")}
        </p>
      ) : null}
    </form>
  );
}

interface KindToggleProps {
  kind: TicketCommentKind;
  onChange: (next: TicketCommentKind) => void;
  showCustomerReply: boolean;
  customerReplyDisabled: boolean;
  isTerminal: boolean;
}

function KindToggle({
  kind,
  onChange,
  showCustomerReply,
  customerReplyDisabled,
  isTerminal,
}: KindToggleProps) {
  const { t } = useTranslation();
  return (
    <RadioGroup
      value={kind}
      onValueChange={(v) => onChange(v as TicketCommentKind)}
      className="flex flex-row gap-4"
    >
      <Label className="flex cursor-pointer items-center gap-2 text-sm">
        <RadioGroupItem value="internal_note" />
        {t("tickets.comments.internalNote")}
      </Label>
      {showCustomerReply ? (
        customerReplyDisabled ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Label className="flex cursor-not-allowed items-center gap-2 text-sm opacity-50">
                    <RadioGroupItem value="customer_reply" disabled />
                    {t("tickets.comments.customerReply")}
                  </Label>
                }
              />
              <TooltipContent>
                {isTerminal
                  ? t("tickets.comments.terminalTooltip")
                  : t("tickets.comments.roleTooltip")}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <Label className="flex cursor-pointer items-center gap-2 text-sm">
            <RadioGroupItem value="customer_reply" />
            {t("tickets.comments.customerReply")}
          </Label>
        )
      ) : null}
    </RadioGroup>
  );
}
