# Handoff: invitation-token-debug

**Tarih:** 2026-05-02 (local-agent)
**Sprint:** 8.3.2 smoke-fix follow-up
**Yazar:** local-agent
**Hedef:** server-agent
**Durum:** open
**Öncelik:** yüksek

## Bağlam

Browser smoke test sırasında: `/admin/tenants` → Demo → "Davet Oluştur" → admin@imga.ai için tenant_admin → davet linki üretildi → gizli pencerede tıklandı → **"Bu davet geçersiz, süresi dolmuş veya kullanılmış"** ekranı.

Token: `sRuoUtyuR7mocPHncTETe0fghj1UKIGef7vygyWHRYU`

## Local code review — masum görünüyor

Frontend (`packages/imga-web/src/hooks/use-invitation.ts:23-26`):

```typescript
return apiRequest<InvitationPreview>(
  `/invitations/${encodeURIComponent(token ?? "")}/preview`,
  { method: "POST", skipAuth: true },
);
```

`secrets.token_urlsafe(32)` çıktısı yalnız `[A-Za-z0-9_-]` karakterleri içerir → URL encoding no-op. Token örneğindeki tüm karakterler bu sınıftan, encoding sorun çıkarmaz.

Backend (`packages/imga-api/src/imga_api/services/invitation_service.py:168-199`):

```python
token_hash = hash_token(plaintext_token)  # SHA-256 deterministic
stmt = select(...).where(Invitation.token_hash == token_hash)
row = ...one_or_none()
if row is None:
    raise InvitationAcceptanceError(...)  # → 404
if accepted_at is not None or expires_at <= now:
    raise InvitationAcceptanceError(...)  # → 404
```

Üç olası 404 sebebi:

1. Row DB'de yok (token hash mismatch — yazma/okuma arasında bir mutation)
2. `accepted_at IS NOT NULL` (ön-tüketim — preview gerçekten consume etmiyor; başka bir route mu çağrıldı?)
3. `expires_at <= now` (TTL hatası — `INVITATION_TTL` 7 gün olmalıydı)

Local'de docker yok; üretim DB'sine erişimim yok. Sunucuda doğrudan teşhis lazım.

## Talep — sunucu agent

Aşağıdaki teşhis komutlarını koş, çıktıyı bu handoff'un "Cevap" bölümüne yapıştır. Hangi kök neden olduğu netleştikten sonra fix tek satır olabilir.

### 1. DB satırı var mı?

```bash
sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml \
  exec postgres psql -U imga_owner -d imga -c "
SELECT
  id,
  tenant_id,
  email,
  role,
  expires_at,
  accepted_at,
  created_at,
  encode(sha256('sRuoUtyuR7mocPHncTETe0fghj1UKIGef7vygyWHRYU'::bytea), 'hex') AS expected_hash,
  token_hash,
  token_hash = encode(sha256('sRuoUtyuR7mocPHncTETe0fghj1UKIGef7vygyWHRYU'::bytea), 'hex')
    AS hash_match
FROM invitations
WHERE email ILIKE 'admin@imga.ai'
ORDER BY created_at DESC
LIMIT 5;
"
```

Üç satırlık çıktı yorumlama:

- `hash_match=true` ama `accepted_at IS NOT NULL` → 2. olası neden (ön-tüketim)
- `hash_match=true` ama `expires_at <= now()` → 3. olası neden (TTL bug)
- `hash_match=false` veya satır yok → 1. olası neden (yazma sırasında token mutation)

### 2. API logları

```bash
sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml \
  logs api --tail 500 | grep -iE "invitation|preview" | tail -50
```

Beklenen: `invitation.create` audit row, sonra `POST /invitations/.../preview` 404. Eğer arada başka bir invitation çağrısı varsa (örn. accept-existing tetiklendi) ön-tüketim doğrulanır.

### 3. Eğer hash_match=true + accepted_at NULL + expires_at gelecekteyse

Demek ki kod yolu doğru, ama bir yerde yanlış şey çağrılıyor. Frontend logging:

```
Browser dev tools → Network → /invitations/<token>/preview çağrısının
Request URL'sini ve Response body'sini handoff'a yapıştır.
```

URL'deki token Display'deki tokenle birebir aynı mı kontrol et — kopyala-yapıştır sırasında bir karakter düşmüş olabilir (özellikle `-` — terminal kopyalarında satır kaymasıyla bölünebilir).

## Fix matrix

| Bulgu | Fix |
|---|---|
| `hash_match=false` | Token kayıt sırasında mutate ediliyor — `email.lower().strip()` benzeri bir helper'a tokenı yanlışlıkla geçirmiş olabiliriz; `create_invitation` import zincirini incele |
| `accepted_at IS NOT NULL` ve preview öncesi accept yok | Preview consume eden bir kod yolu var — doğrudan `invitation_service.py` mutate eden başka bir method ara |
| `expires_at <= now()` | `INVITATION_TTL` constant değeri (services/__init__.py'da) yanlış — 7 gün değil 0 gün veya `timedelta(seconds=N)` olabilir |
| Token URL'de farklı | Frontend kopyala-yapıştır UX bug; tekrar üretip dikkatle dene + DialogContent'in CSS truncate sınıfı clipboard'a etki etmez ama bir kez doğrulayalım |

## Production etkisi

**DEMO BLOCKER.** Yeni tenant'a kullanıcı eklenemez. Mevcut tenant'lar etkilenmez (kendi davet token'ları vardı).

Geçici workaround (kabul edilemez ama kritikse): Süper-admin DB'den manuel `INSERT INTO user_tenants ...` yaparak admin@imga.ai'yi Demo tenant'a tenant_admin olarak ekler. Davet flow'u hâlâ kırık ama prod'da kullanıcı bekleyen iş varsa bu unblock eder.

## İlgili dosyalar (kod referansı)

- `packages/imga-api/src/imga_api/security/tokens.py` — `secrets.token_urlsafe(32)` + SHA-256
- `packages/imga-api/src/imga_api/services/invitation_service.py:112-146` — create
- `packages/imga-api/src/imga_api/services/invitation_service.py:168-214` — preview
- `packages/imga-api/src/imga_api/routes/invitations.py:103-128` — preview route
- `packages/imga-web/src/components/admin/tenant-create-dialog.tsx:376-384` — `inviteUrl` builder
- `packages/imga-web/src/hooks/use-invitation.ts:19-32` — preview hook

## Cevap

(server-agent doldurur)

---
