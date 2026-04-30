import { ProtectedRoute } from "@/components/auth/protected-route";

/**
 * Route-group layout for every page that requires a logged-in user.
 * The full app shell (sidebar + topbar + tenant switcher) is wired
 * up in Sprint 7.6.2; for now the layout just gates with
 * ProtectedRoute so the placeholder dashboard cannot be reached
 * without a session.
 */
export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>;
}
