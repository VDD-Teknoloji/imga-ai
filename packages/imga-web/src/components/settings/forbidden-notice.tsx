import { ShieldAlert } from "lucide-react";

export function ForbiddenNotice() {
  return (
    <main className="mx-auto flex w-full max-w-md flex-col items-center gap-3 p-12 text-center">
      <ShieldAlert className="text-muted-foreground size-10" aria-hidden />
      <h1 className="text-2xl font-semibold tracking-tight">Yetkiniz yok</h1>
      <p className="text-muted-foreground text-sm">
        Tenant yapılandırması yalnızca yöneticiler tarafından düzenlenebilir.
        Yetki için tenant yöneticinize başvurun.
      </p>
    </main>
  );
}
