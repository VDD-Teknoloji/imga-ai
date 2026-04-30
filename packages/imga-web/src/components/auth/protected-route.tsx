"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthStore } from "@/lib/auth-store";

/**
 * Gate for everything inside (authenticated)/. Redirects to /login
 * once initialize() has settled and the user is still null. Renders
 * a spinner placeholder until isInitialized flips so we don't flash
 * the dashboard for unauthenticated visitors.
 */
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const isInitialized = useAuthStore((s) => s.isInitialized);

  useEffect(() => {
    if (isInitialized && !user) {
      router.replace("/login");
    }
  }, [user, isInitialized, router]);

  if (!isInitialized) {
    return (
      <div className="text-muted-foreground flex min-h-screen items-center justify-center text-sm">
        Yükleniyor...
      </div>
    );
  }

  if (!user) {
    // The replace() above is in flight; render nothing to avoid flash.
    return null;
  }

  return <>{children}</>;
}
