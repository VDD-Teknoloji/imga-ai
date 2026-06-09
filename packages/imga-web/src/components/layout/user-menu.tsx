"use client";

import { ChevronsUpDown, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/utils";

interface UserMenuProps {
  collapsed: boolean;
}

/**
 * Sticky bottom corner of the sidebar. Shows the user's initials in
 * an avatar, expands to a dropdown with "Çıkış yap" today; future
 * items (profile, password change shortcut) plug in here.
 */
export function UserMenu({ collapsed }: UserMenuProps) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  if (!user) return null;

  const initials = computeInitials(user.full_name, user.email);

  async function handleLogout() {
    try {
      await logout();
    } catch {
      toast.error("Çıkış sırasında hata oluştu");
      return;
    }
    router.replace("/login");
  }

  const triggerElement = (
    <Button
      variant="ghost"
      aria-label={`Kullanıcı menüsü: ${user.full_name}`}
      className={cn(
        "hover:bg-sidebar-accent h-12 w-full justify-start gap-3 px-2",
        collapsed && "justify-center px-0",
      )}
    >
      <Avatar className="size-8">
        <AvatarFallback className="bg-primary text-primary-foreground text-xs">
          {initials}
        </AvatarFallback>
      </Avatar>
      {collapsed ? null : (
        <span className="flex min-w-0 flex-1 flex-col items-start text-left">
          <span className="w-full truncate text-sm font-medium">{user.full_name}</span>
          <span className="text-sidebar-foreground/60 w-full truncate text-xs">{user.email}</span>
        </span>
      )}
      {collapsed ? null : <ChevronsUpDown className="size-4 shrink-0 opacity-60" aria-hidden />}
    </Button>
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={triggerElement} />
      <DropdownMenuContent align="end" side="top" className="w-56">
        {/* Base UI's MenuGroupLabel zorunlu olarak Menu.Group içinde
            yaşar; çıplak `DropdownMenuLabel` Base UI error #31'i
            ("MenuGroupRootContext is missing") tetikler. */}
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex flex-col">
            <span className="truncate font-medium">{user.full_name}</span>
            <span className="text-muted-foreground truncate text-xs font-normal">{user.email}</span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={handleLogout}>
          <LogOut className="size-4" aria-hidden />
          Çıkış yap
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function computeInitials(fullName: string, email: string): string {
  const source = fullName.trim().length > 0 ? fullName : email;
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) {
    const first = parts[0] ?? "";
    return first.slice(0, 2).toUpperCase();
  }
  const first = parts[0] ?? "";
  const last = parts[parts.length - 1] ?? "";
  return `${first.charAt(0)}${last.charAt(0)}`.toUpperCase();
}
