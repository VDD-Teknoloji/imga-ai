import { AppShell } from "@/components/layout/app-shell";
import { ProtectedRoute } from "@/components/auth/protected-route";

/**
 * Route-group layout for every page that requires a logged-in user.
 * ProtectedRoute redirects to /login if the auth store settles
 * user-less; AppShell paints the sidebar + mobile topbar + main
 * content frame around whatever the page renders.
 */
export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}
