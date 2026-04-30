"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { AuthProvider } from "@/components/auth/auth-provider";
import { Toaster } from "@/components/ui/sonner";
import { createQueryClient } from "@/lib/query-client";

/**
 * Single client-only wrapper that mounts every cross-cutting provider
 * the rest of the app expects: TanStack Query, the auth store
 * initializer, and the Sonner toast portal. Lives here (rather than
 * inline in app/layout.tsx) so the root layout can stay a server
 * component if we later want it to be.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => createQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
      <Toaster richColors position="top-right" />
    </QueryClientProvider>
  );
}
