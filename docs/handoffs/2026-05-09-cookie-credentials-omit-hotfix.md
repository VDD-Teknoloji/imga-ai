# Handoff: cookie-credentials-omit-hotfix

**Tarih:** 2026-05-09
**Sprint:** 9.0.6 hotfix
**Yazar:** server-agent
**Hedef:** local-agent
**Durum:** open
**Öncelik:** kritik

## Bağlam

Sprint 9.0.6 (cdc296c) production deploy sonrası login bug:

- Cookie'ler browser'a oturmuyor → /auth/me 401
- 2 katmanlı bug:
  1. Backend env eksik: IMGA_COOKIE_SECURE/DOMAIN/SAMESITE production override'ı yoktu
  2. Frontend credentials:"omit" — skipAuth=true (login + invitation 3 yer) hem outbound hem Set-Cookie disregard ediyor

## Hotfix uygulandı

### Backend env (host-side, git'te yok)

`/etc/imga/{production,staging}/api.env`'e eklendi:

```
IMGA_COOKIE_SECURE=true
IMGA_COOKIE_DOMAIN=.imga.ai
IMGA_COOKIE_SAMESITE=lax
```

api force-recreate ile loaded.

### Frontend (working tree, push pending)

`packages/imga-web/src/lib/api-client.ts:57`:

```diff
-    credentials: options.skipAuth ? "omit" : "include",
+    credentials: "include",
```

Sprint 9.0.6 B'de bearer kaldırıldı, skipAuth flag'i artık no-op (typecheck gerek için kalıyor).

## Doğrulama

- Production login → OK (kullanıcı tarafından)
- Staging login → OK
- Set-Cookie response: Domain=.imga.ai, HttpOnly, Secure, SameSite=lax, Max-Age 900/604800
- /auth/me roundtrip → 200

## Talep

Local agent: working tree fix'i commit + push.

## Cevap

(local-agent: commit hash + push)
