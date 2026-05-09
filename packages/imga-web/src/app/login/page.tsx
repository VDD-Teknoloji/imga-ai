"use client";

import { AlertCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";

export default function LoginPage() {
  // Sprint 9.1 hotfix — useSearchParams forces a Suspense boundary
  // under Next 16's app router; the form lives in the inner
  // component so the Suspense wrapper renders the same skeleton on
  // first paint regardless of query-param state.
  return (
    <Suspense fallback={<LoginSkeleton />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginSkeleton() {
  return (
    <div className="bg-muted flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">imga.ai</CardTitle>
          <CardDescription>Yükleniyor…</CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const login = useAuthStore((s) => s.login);
  const isLoading = useAuthStore((s) => s.isLoading);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Sprint 9.1 hotfix — when the api-client's session-expired hook
  // fires, the user lands here with ?expired=1. Surface a banner so
  // the user understands why they're back at login (vs a confused
  // "did the page refresh?").
  const sessionExpired = searchParams.get("expired") === "1";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 401
          ? "E-posta veya şifre hatalı."
          : "Giriş yapılamadı, lütfen daha sonra tekrar deneyin.";
      toast.error("Giriş başarısız", { description: message });
    }
  }

  return (
    <div className="bg-muted flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">imga.ai</CardTitle>
          <CardDescription>Hesabınıza giriş yapın</CardDescription>
        </CardHeader>
        <CardContent>
          {sessionExpired && (
            <div
              role="status"
              className="mb-4 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
            >
              <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <p>Oturumunuz sona erdi. Lütfen tekrar giriş yapın.</p>
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">E-posta</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoComplete="email"
                disabled={isLoading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Şifre</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                autoComplete="current-password"
                disabled={isLoading}
              />
            </div>
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? "Giriş yapılıyor..." : "Giriş yap"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
