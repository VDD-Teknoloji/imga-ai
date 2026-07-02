"use client";

import Link from "next/link";

import { TicketStateBadge } from "@/components/dashboard/ticket-state-badge";
import { TicketPriorityBadge } from "@/components/tickets/ticket-priority-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuthStore } from "@/lib/auth-store";
import { formatRelativeDate } from "@/lib/date-format";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { Ticket } from "@/lib/types";

interface TicketListTableProps {
  tickets: ReadonlyArray<Ticket>;
  categoryLabelMap: ReadonlyMap<string, string>;
}

/**
 * Read-only table. Each row is a clickable link to /tickets/{id}.
 * Assignee column shows "Sana" / "Atanmamış" / "Başka" — full
 * assignee name lookup needs the Sprint 7.5.5 tenant directory
 * endpoint (roadmap A7).
 */
export function TicketListTable({ tickets, categoryLabelMap }: TicketListTableProps) {
  const { t } = useTranslation();
  const currentUserId = useAuthStore((s) => s.user?.id);

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("tickets.list.colTitle")}</TableHead>
            <TableHead className="hidden md:table-cell">{t("tickets.list.colCategory")}</TableHead>
            <TableHead>{t("tickets.list.colState")}</TableHead>
            <TableHead className="hidden sm:table-cell">{t("tickets.list.colPriority")}</TableHead>
            <TableHead className="hidden lg:table-cell">{t("tickets.list.colAssignee")}</TableHead>
            <TableHead className="hidden xl:table-cell">{t("tickets.list.colUpdated")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tickets.map((ticket) => (
            <TableRow key={ticket.id} className="cursor-pointer">
              <TableCell className="max-w-[24rem] font-medium">
                <Link
                  href={`/tickets/${ticket.id}`}
                  className="hover:text-primary block truncate"
                >
                  {ticket.title}
                </Link>
              </TableCell>
              <TableCell className="text-muted-foreground hidden md:table-cell">
                {categoryLabelMap.get(ticket.category_id) ?? "—"}
              </TableCell>
              <TableCell>
                <TicketStateBadge state={ticket.state} />
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <TicketPriorityBadge priority={ticket.priority} />
              </TableCell>
              <TableCell className="text-muted-foreground hidden text-xs lg:table-cell">
                {t(assigneeLabelKey(ticket.assigned_to_user_id, currentUserId))}
              </TableCell>
              <TableCell className="text-muted-foreground hidden text-xs xl:table-cell">
                {formatRelativeDate(ticket.last_state_change_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function assigneeLabelKey(
  assigneeId: string | null,
  currentUserId: string | undefined,
): string {
  if (assigneeId === null) return "tickets.common.unassigned";
  if (currentUserId && assigneeId === currentUserId) return "tickets.list.assigneeYou";
  return "tickets.list.assigneeOther";
}
