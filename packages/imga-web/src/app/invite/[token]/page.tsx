"use client";

import { Building2, CalendarClock, CheckCircle2, MailCheck, ShieldAlert } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useInvitationPreview } from "@/hooks/use-invitation";
import { ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { formatFullDate } from "@/lib/date-format";
import type { InvitationPreview, UserTenantRole } from "@/lib/types";
import { USER_ROLE_LABELS } from "@/lib/user-helpers";

/**
 * Public invite-accept page. NOT wrapped in ProtectedRoute (lives
 * outside the (authenticated) group), so a logged-out invitee can
 * land here directly from the email link.
 *
 * Flow:
 *   1. POST /invitations/{token}/preview — fetches tenant + role +
 *      email_exists. Generic 404 for any failure path (token bad /
 *      expired / already accepted) — same opaque message defeats
 *      probing.
 *   2. Branch on email_exists:
 *        false → "new account" form (full_name + password) →
 *                 POST /accept → tokens stored + redirect to "/".
 *        true  → "existing user" form (password only) → user must
 *                 log in first if they aren't already, then re-auth
 *                 password against POST /accept-existing.
 *   3. Errors map per-status: 401 wrong password, 403 email mismatch,
 *      404 invalid/expired/consumed.
 */
export default function InviteAcceptPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const preview = useInvitationPreview(token);

  return (
    <div className="bg-muted flex min-h-screen items-center justify-center px-4 py-8">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-2xl">imga.ai</CardTitle>
          <CardDescription>Davet linki</CardDescription>
        </CardHeader>
        <CardContent>
          {preview.isLoading ? (
            <PreviewSkeleton />
          ) : preview.isError ? (
            <InvalidTokenView />
          ) : preview.data ? (
            <ValidInviteView preview={preview.data} token={token} />
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

// --- skeleton + invalid ---------------------------------------------------

function PreviewSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <div className="space-y-2 pt-2">
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
      </div>
    </div>
  );
}

function InvalidTokenView() {
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <ShieldAlert className="text-destructive mt-0.5 size-5 shrink-0" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">Bu davet geçersiz veya süresi dolmuş.</p>
          <p className="text-muted-foreground text-sm">
            Lütfen tenant yöneticinizle iletişime geçip yeni bir davet
            isteyin.
          </p>
        </div>
      </div>
      <Button
        variant="outline"
        render={<a href="/login" />}
        className="w-full"
      >
        Giriş ekranına dön
      </Button>
    </div>
  );
}

// --- valid invite shell ---------------------------------------------------

interface ValidInviteProps {
  preview: InvitationPreview;
  token: string;
}

function ValidInviteView({ preview, token }: ValidInviteProps) {
  return (
    <div className="space-y-5">
      <PreviewHeader preview={preview} />
      {preview.email_exists ? (
        <ExistingUserAcceptForm preview={preview} token={token} />
      ) : (
        <NewUserAcceptForm preview={preview} token={token} />
      )}
    </div>
  );
}

function PreviewHeader({ preview }: { preview: InvitationPreview }) {
  return (
    <div className="bg-muted/40 space-y-2 rounded-md border p-3 text-sm">
      <div className="flex items-center gap-2">
        <Building2 className="text-muted-foreground size-4" aria-hidden />
        <span className="font-medium">{preview.tenant_name}</span>
        <Badge variant="secondary" className="ml-auto">
          {USER_ROLE_LABELS[preview.role as UserTenantRole]}
        </Badge>
      </div>
      <div className="text-muted-foreground flex items-center gap-2 text-xs">
        <MailCheck className="size-3.5" aria-hidden />
        Davet edilen: <span className="text-foreground">{preview.invited_email}</span>
      </div>
      <div className="text-muted-foreground flex items-center gap-2 text-xs">
        <CalendarClock className="size-3.5" aria-hidden />
        Geçerlilik: {formatFullDate(preview.expires_at)}
      </div>
    </div>
  );
}

// --- new user form --------------------------------------------------------

function NewUserAcceptForm({ preview, token }: ValidInviteProps) {
  const router = useRouter();
  const acceptAsNewUser = useAuthStore((s) => s.acceptInvitationAsNewUser);
  const isLoading = useAuthStore((s) => s.isLoading);

  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (password !== passwordConfirm) {
      toast.error("Şifreler eşleşmiyor.");
      return;
    }
    if (password.length < 8) {
      toast.error("Şifre en az 8 karakter olmalı.");
      return;
    }
    try {
      await acceptAsNewUser(token, fullName.trim(), password);
      toast.success("Hesap oluşturuldu", {
        description: `${preview.tenant_name} ekibine hoş geldin.`,
      });
      router.replace("/");
    } catch (err) {
      toast.error("Davet kabul edilemedi", {
        description: describeAcceptError(err),
      });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm font-medium">Yeni hesap oluştur</p>

      <div className="space-y-2">
        <Label htmlFor="full-name">Tam adınız</Label>
        <Input
          id="full-name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          minLength={1}
          maxLength={255}
          required
          autoComplete="name"
          disabled={isLoading}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">Şifre</Label>
        <Input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={8}
          required
          autoComplete="new-password"
          disabled={isLoading}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password-confirm">Şifre tekrar</Label>
        <Input
          id="password-confirm"
          type="password"
          value={passwordConfirm}
          onChange={(e) => setPasswordConfirm(e.target.value)}
          minLength={8}
          required
          autoComplete="new-password"
          disabled={isLoading}
        />
      </div>

      <Button
        type="submit"
        className="w-full gap-2"
        disabled={isLoading || fullName.trim() === ""}
      >
        {isLoading ? "Hesap oluşturuluyor..." : "Daveti kabul et"}
        <CheckCircle2 className="size-4" aria-hidden />
      </Button>
    </form>
  );
}

// --- existing user form ---------------------------------------------------

function ExistingUserAcceptForm({ preview, token }: ValidInviteProps) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const login = useAuthStore((s) => s.login);
  const joinTenant = useAuthStore((s) => s.joinTenantViaInvitation);
  const isLoading = useAuthStore((s) => s.isLoading);

  // Email is fixed by the invitation; only the password is needed.
  // If the visitor isn't authenticated yet, we run /auth/login first
  // (with the invited_email + password) and then call /accept-existing
  // with the same password. From the user's POV it's a single button
  // press.
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isAuthedAsInvitee =
    user !== null && user.email.toLowerCase() === preview.invited_email.toLowerCase();
  const isAuthedAsOther =
    user !== null && user.email.toLowerCase() !== preview.invited_email.toLowerCase();

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (!isAuthedAsInvitee) {
        // Not logged in (or logged in as someone else). Sign in as
        // the invited account first; the same password is replayed
        // against /accept-existing immediately after.
        await login(preview.invited_email, password);
      }
      await joinTenant(token, password);
      toast.success("Davet kabul edildi", {
        description: `${preview.tenant_name} artık tenant listende.`,
      });
      router.replace("/");
    } catch (err) {
      toast.error("Davet kabul edilemedi", {
        description: describeAcceptError(err),
      });
    } finally {
      setSubmitting(false);
    }
  }

  const busy = submitting || isLoading;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1">
        <p className="text-sm font-medium">Mevcut hesap ile katıl</p>
        <p className="text-muted-foreground text-xs">
          Bu e-posta zaten kayıtlı. Şifrenle doğrulayıp tenant&apos;a
          ekleneceksin — yeni hesap açılmıyor.
        </p>
      </div>

      {isAuthedAsOther ? (
        <div className="bg-amber-50 dark:bg-amber-950/30 flex items-start gap-2 rounded-md border border-amber-500/30 p-3 text-xs">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden />
          <p>
            Şu an <span className="font-medium">{user?.email}</span> hesabıyla
            giriş yapmışsın ama davet{" "}
            <span className="font-medium">{preview.invited_email}</span> içindi.
            Aşağıya o hesabın şifresini gir; oturum yeni hesaba geçecek.
          </p>
        </div>
      ) : null}

      <div className="space-y-2">
        <Label htmlFor="invitee-email">E-posta</Label>
        <Input
          id="invitee-email"
          type="email"
          value={preview.invited_email}
          readOnly
          disabled
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="reauth-password">Şifre</Label>
        <Input
          id="reauth-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
          disabled={busy}
        />
      </div>

      <Button
        type="submit"
        className="w-full gap-2"
        disabled={busy || password === ""}
      >
        {busy ? "Doğrulanıyor..." : "Hesabımla daveti kabul et"}
        <CheckCircle2 className="size-4" aria-hidden />
      </Button>
    </form>
  );
}

// --- error description ----------------------------------------------------

function describeAcceptError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Şifre hatalı.";
    if (err.status === 403) return "Bu davet farklı bir e-posta için.";
    if (err.status === 404) return "Davet geçersiz, süresi dolmuş veya zaten kullanılmış.";
    if (err.status === 409) return "Bu e-posta zaten kayıtlı; mevcut hesabınla katıl.";
  }
  return "Beklenmeyen bir hata oluştu, lütfen tekrar dene.";
}
