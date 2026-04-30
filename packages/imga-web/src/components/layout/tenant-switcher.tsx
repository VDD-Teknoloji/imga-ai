"use client";

import { Building2, Check, ChevronsUpDown } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
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

  const activeTenantName = activeContext?.tenant_name ?? "Tenant seçilmedi";
  const activeTenantId = activeContext?.tenant_id ?? null;

  // Single-tenant users get a static badge — switching is meaningless.
  if (availableTenants.length <= 1) {
    return (
      <div
        className={cn(
          "bg-card flex h-10 items-center gap-2 rounded-md border px-3 text-sm",
          collapsed && "justify-center px-0",
        )}
        aria-label={`Aktif tenant: ${activeTenantName}`}
      >
        <Building2 className="text-muted-foreground size-4 shrink-0" aria-hidden />
        {collapsed ? null : <span className="truncate">{activeTenantName}</span>}
      </div>
    );
  }

  async function handleSelect(tenantId: string) {
    if (tenantId === activeTenantId) {
      setOpen(false);
      return;
    }
    setIsSwitching(true);
    try {
      await switchTenant(tenantId);
      toast.success("Tenant değiştirildi");
    } catch {
      toast.error("Tenant değiştirilemedi");
    } finally {
      setIsSwitching(false);
      setOpen(false);
    }
  }

  const triggerElement = (
    <Button
      variant="outline"
      aria-expanded={open}
      aria-label={`Aktif tenant: ${activeTenantName}. Değiştirmek için açın.`}
      disabled={isSwitching}
      className={cn(
        "h-10 w-full justify-between gap-2 px-3 font-medium",
        collapsed && "justify-center px-0",
      )}
    >
      <span className="flex min-w-0 items-center gap-2">
        <Building2 className="text-muted-foreground size-4 shrink-0" aria-hidden />
        {collapsed ? null : <span className="truncate">{activeTenantName}</span>}
      </span>
      {collapsed ? null : <ChevronsUpDown className="size-4 shrink-0 opacity-60" aria-hidden />}
    </Button>
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={triggerElement} />
      <PopoverContent align="start" className="w-[260px] p-0">
        <Command>
          <CommandInput placeholder="Tenant ara..." />
          <CommandList>
            <CommandEmpty>Eşleşen tenant yok.</CommandEmpty>
            <CommandGroup>
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
                    <span className="text-muted-foreground truncate text-xs">{tenant.role}</span>
                  </span>
                  {tenant.id === activeTenantId ? (
                    <Check className="text-primary size-4" aria-hidden />
                  ) : null}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
