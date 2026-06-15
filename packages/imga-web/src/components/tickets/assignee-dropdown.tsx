"use client";

import { Check, ChevronDown, UserMinus, UserRound } from "lucide-react";
import { useMemo, useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
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
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { useTenantMembers } from "@/hooks/use-tenant-members";
import { useTicketAssign } from "@/hooks/use-ticket-mutations";
import { useAuthStore } from "@/lib/auth-store";
import type { TenantMember } from "@/lib/types";
import { USER_ROLE_LABELS, userInitials } from "@/lib/user-helpers";
import { cn } from "@/lib/utils";

interface AssigneeDropdownProps {
  ticketId: string;
  currentAssigneeId: string | null;
  /** Tenant_admin can reassign other people's tickets. Analysts can
   * only self-assign or release their own. */
  isAdmin: boolean;
  /** Set false on CLOSED / CANCELLED tickets — assignment is frozen
   * once the ticket is terminal. */
  enabled: boolean;
}

/**
 * Assignee picker for the ticket detail side panel. Sprint 7.5.5
 * shipped GET /tenants/me/users; this is the first consumer.
 *
 * Layout: trigger button shows the current assignee (or "Atanmamış");
 * the popover shows a searchable command list with "Atanmamış" as a
 * special top option followed by tenant members. Self carries a
 * "Sen" badge; every row shows the member's role.
 */
export function AssigneeDropdown({
  ticketId,
  currentAssigneeId,
  isAdmin,
  enabled,
}: AssigneeDropdownProps) {
  const [open, setOpen] = useState(false);
  const currentUserId = useAuthStore((s) => s.user?.id);
  const activeTenantId = useAuthStore((s) => s.activeContext?.tenant_id);
  const members = useTenantMembers(activeTenantId);
  const assign = useTicketAssign();

  const memberMap = useMemo<ReadonlyMap<string, TenantMember>>(() => {
    const map = new Map<string, TenantMember>();
    for (const m of members.data ?? []) {
      map.set(m.user_id, m);
    }
    return map;
  }, [members.data]);

  const currentMember = currentAssigneeId
    ? memberMap.get(currentAssigneeId)
    : undefined;

  // Analyst can pick from: themselves, "unassigned" (release their
  // own), nothing else — no list of other members. Admin sees the
  // full list. Server enforces this; UI mirrors so we don't surface
  // dead options.
  const selectableMembers = useMemo<ReadonlyArray<TenantMember>>(() => {
    if (members.data === undefined) return [];
    if (isAdmin) return members.data;
    if (currentUserId === undefined) return [];
    return members.data.filter((m) => m.user_id === currentUserId);
  }, [members.data, isAdmin, currentUserId]);

  function handleSelect(userId: string | null) {
    setOpen(false);
    if (userId === currentAssigneeId) return;
    assign.mutate({ ticketId, assigneeUserId: userId });
  }

  const triggerLabel = currentMember
    ? currentMember.full_name
    : currentAssigneeId
      ? "Bilinmeyen kullanıcı"
      : "Atanmamış";

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              className="h-9 w-full justify-between gap-2"
              disabled={!enabled || assign.isPending}
            >
              <span className="flex items-center gap-2 truncate">
                {currentAssigneeId ? (
                  <Avatar size="sm" className="size-5">
                    <AvatarFallback className="text-[10px]">
                      {userInitials({
                        full_name: currentMember?.full_name,
                        email: currentMember?.email,
                      })}
                    </AvatarFallback>
                  </Avatar>
                ) : (
                  <UserMinus className="text-muted-foreground size-4" aria-hidden />
                )}
                <span className="truncate">{triggerLabel}</span>
                {currentAssigneeId === currentUserId ? (
                  <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                    Sen
                  </Badge>
                ) : null}
              </span>
              <ChevronDown
                className="text-muted-foreground size-4 shrink-0"
                aria-hidden
              />
            </Button>
          }
        />
        <PopoverContent align="start" className="w-[280px] p-0">
          {members.isLoading ? (
            <div className="space-y-2 p-3">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
            </div>
          ) : members.isError ? (
            <p className="text-destructive p-3 text-xs">
              Kullanıcı listesi yüklenemedi.
            </p>
          ) : (
            <Command>
              <CommandInput placeholder="Kullanıcı ara..." />
              <CommandList>
                <CommandEmpty>Eşleşme yok.</CommandEmpty>

                <CommandGroup>
                  <CommandItem
                    value="atanmamış unassigned"
                    onSelect={() => handleSelect(null)}
                    className="flex items-center gap-2"
                  >
                    <UserMinus className="text-muted-foreground size-4" aria-hidden />
                    <span className="flex-1">Atanmamış</span>
                    {currentAssigneeId === null ? (
                      <Check className="text-primary size-4" aria-hidden />
                    ) : null}
                  </CommandItem>
                </CommandGroup>

                {selectableMembers.length > 0 ? (
                  <CommandGroup heading="Kullanıcılar">
                    {selectableMembers.map((m) => (
                      <CommandItem
                        key={m.user_id}
                        value={`${m.full_name} ${m.email}`}
                        onSelect={() => handleSelect(m.user_id)}
                        className="flex items-center gap-2"
                      >
                        <Avatar size="sm" className="size-6">
                          <AvatarFallback className="text-[10px]">
                            {userInitials({
                              full_name: m.full_name,
                              email: m.email,
                            })}
                          </AvatarFallback>
                        </Avatar>
                        <span className="flex min-w-0 flex-col">
                          <span className="flex items-center gap-1.5 truncate text-sm">
                            {m.full_name}
                            {m.user_id === currentUserId ? (
                              <Badge
                                variant="secondary"
                                className="h-4 px-1 text-[10px]"
                              >
                                Sen
                              </Badge>
                            ) : null}
                          </span>
                          <span
                            className={cn(
                              "text-muted-foreground truncate text-xs",
                            )}
                          >
                            {USER_ROLE_LABELS[m.role]} · {m.email}
                          </span>
                        </span>
                        {currentAssigneeId === m.user_id ? (
                          <Check className="text-primary ml-auto size-4" aria-hidden />
                        ) : null}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ) : null}

                {!isAdmin && selectableMembers.length === 0 ? (
                  <p className="text-muted-foreground p-3 text-xs">
                    Sadece kurum yöneticisi başka kullanıcıya atayabilir.
                    <UserRound className="ml-1 inline size-3" aria-hidden />
                  </p>
                ) : null}
              </CommandList>
            </Command>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}
