"use client";

import { Building2, Check, ChevronsUpDown, MailPlus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { TenantInviteAcceptDialog } from "@/components/layout/tenant-invite-accept-dialog";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/utils";

interface TenantSwitcherProps {
  /** When the parent sidebar is collapsed, render an icon-only
   * trigger that opens the popover sideways. */
  collapsed: boolean;
}

export function TenantSwitcher({ collapsed }: TenantSwitcherProps) {
  const activeContext = useAuthStore((s) => s.activeContext);
  const availableTenants = useAuthStore((s) => s.availableTenants);
  const switchTenant = useAuthStore((s) => s.switchTenant);

  const [open, setOpen] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);

  const activeTenantName = activeContext?.tenant_name ?? "Kurum seçilmedi";
  const activeTenantId = activeContext?.tenant_id ?? null;

  // Sprint 7.7.3: even single-tenant users see the popover so
  // "+ Yeni davet kabul et" is always reachable. The popover still
  // lists the active tenant — the dropdown isn't strictly a
  // "switcher" anymore, more of a "tenants menu".

  async function handleSelect(tenantId: string) {
    if (tenantId === activeTenantId) {
      setOpen(false);
      return;
    }
    setIsSwitching(true);
    try {
      await switchTenant(tenantId);
      toast.success("Kurum değiştirildi");
    } catch {
      toast.error("Kurum değiştirilemedi");
    } finally {
      setIsSwitching(false);
      setOpen(false);
    }
  }

  const triggerElement = (
    <Button
      variant="outline"
      aria-expanded={open}
      aria-label={`Aktif kurum: ${activeTenantName}. Değiştirmek için açın.`}
      disabled={isSwitching}
      className={cn(
        "h-10 w-full justify-between gap-2 px-3 font-medium",
        // Sprint 10.2 — lacivert rail üstünde outline buton soluk
        // kalıyordu; trigger sidebar token'larıyla boyanır.
        "border-sidebar-border bg-sidebar-accent/60 text-sidebar-foreground",
        "hover:bg-sidebar-accent hover:text-sidebar-foreground",
        collapsed && "justify-center px-0",
      )}
    >
      <span className="flex min-w-0 items-center gap-2">
        <Building2 className="text-sidebar-foreground/60 size-4 shrink-0" aria-hidden />
        {collapsed ? null : <span className="truncate">{activeTenantName}</span>}
      </span>
      {collapsed ? null : <ChevronsUpDown className="size-4 shrink-0 opacity-60" aria-hidden />}
    </Button>
  );

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger render={triggerElement} />
        <PopoverContent align="start" className="w-[260px] p-0">
          <Command>
            {availableTenants.length > 1 ? (
              <CommandInput placeholder="Kurum ara..." />
            ) : null}
            <CommandList>
              <CommandEmpty>Eşleşen kurum yok.</CommandEmpty>
              <CommandGroup heading="Mevcut kurumlar">
                {availableTenants.map((tenant) => (
                  <CommandItem
                    key={tenant.id}
                    value={`${tenant.name} ${tenant.slug}`}
                    onSelect={() => handleSelect(tenant.id)}
                    disabled={isSwitching}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{tenant.name}</span>
                      <span className="text-muted-foreground truncate text-xs">
                        {tenant.role}
                      </span>
                    </span>
                    {tenant.id === activeTenantId ? (
                      <Check className="text-primary size-4" aria-hidden />
                    ) : null}
                  </CommandItem>
                ))}
              </CommandGroup>
              <CommandSeparator />
              <CommandGroup>
                <CommandItem
                  value="yeni davet kabul et invite accept"
                  onSelect={() => {
                    setOpen(false);
                    setInviteDialogOpen(true);
                  }}
                  className="flex items-center gap-2"
                >
                  <MailPlus
                    className="text-muted-foreground size-4"
                    aria-hidden
                  />
                  <span>Yeni davet kabul et</span>
                </CommandItem>
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      <TenantInviteAcceptDialog
        open={inviteDialogOpen}
        onOpenChange={setInviteDialogOpen}
      />
    </>
  );
}
