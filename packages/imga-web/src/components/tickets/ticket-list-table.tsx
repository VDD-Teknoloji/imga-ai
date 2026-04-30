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
  const currentUserId = useAuthStore((s) => s.user?.id);

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Başlık</TableHead>
            <TableHead className="hidden md:table-cell">Kategori</TableHead>
            <TableHead>Durum</TableHead>
            <TableHead className="hidden sm:table-cell">Öncelik</TableHead>
            <TableHead className="hidden lg:table-cell">Atanan</TableHead>
            <TableHead className="hidden xl:table-cell">Son güncelleme</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tickets.map((t) => (
            <TableRow key={t.id} className="cursor-pointer">
              <TableCell className="max-w-[24rem] font-medium">
                <Link
                  href={`/tickets/${t.id}`}
                  className="hover:text-primary block truncate"
                >
                  {t.title}
                </Link>
              </TableCell>
              <TableCell className="text-muted-foreground hidden md:table-cell">
                {categoryLabelMap.get(t.category_id) ?? "—"}
              </TableCell>
              <TableCell>
                <TicketStateBadge state={t.state} />
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <TicketPriorityBadge priority={t.priority} />
              </TableCell>
              <TableCell className="text-muted-foreground hidden text-xs lg:table-cell">
                {assigneeLabel(t.assigned_to_user_id, currentUserId)}
              </TableCell>
              <TableCell className="text-muted-foreground hidden text-xs xl:table-cell">
                {formatRelativeDate(t.last_state_change_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function assigneeLabel(assigneeId: string | null, currentUserId: string | undefined): string {
  if (assigneeId === null) return "Atanmamış";
  if (currentUserId && assigneeId === currentUserId) return "Sana";
  return "Başka";
}

function formatRelativeDate(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  if (diffHours < 1) return "az önce";
  if (diffHours < 24) return `${diffHours} sa önce`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays} gün önce`;
  return date.toLocaleDateString("tr-TR", { year: "numeric", month: "short", day: "numeric" });
}
