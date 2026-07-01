# `ApiTokenRecord` — Migration & Auth Tasarımı (design doc)

**Tarih:** 2026-07-01 · **Faz:** N+0 · **Statü:** TASARIM (kod değil)
**Amaç:** AsakAI ⇒ İmga v1 için kiracı-başına, uzun ömürlü, opak API token'ı.
**Şablon:** `packages/imga-api/.../routes/tenant_llm_credentials.py` + `TenantLlmCredential`
(create-once-plaintext, last4, RLS+FORCE, role-gated) — kanıtlanmış deseni klonla.
**RLS konvansiyonu referansı:** migration 0006 (`current_setting('app.current_tenant_id')::uuid`).

> Bu doküman N+1'de yazılacak Alembic migration'ı + auth katmanını **tanımlar**;
> kararlar [n0-response §1.4–1.6](2026-07-01-asakai-v1-n0-response.md) ile hizalıdır.

---

## 1. Tasarım kararları (özet)

| Konu | Karar | Gerekçe |
|---|---|---|
| Token biçimi | **Opak** rastgele (`secrets.token_urlsafe`), DB'de hash'li | rotate/revoke için otoriter; stateless api-JWT iptal edilemez |
| Önek | `imga_sk_live_` / `imga_sk_test_` | staging↔prod token karışmasını yapısal reddet |
| At-rest | **HMAC-SHA256(pepper)**, `hmac.compare_digest` | Argon2 auth sıcak-yolu için yavaş; HMAC sabit-zaman + O(1) lookup |
| Yetki | **`service_account` scope seti** (yeni), `tenant_admin`/`analyst` DEĞİL | least-privilege; sızan token kurum ele geçiremesin |
| Kapsam | tenant-scoped, `is_super_admin=False` invariant | süper-admin token'ı üretilmesi imkânsız |
| TTL | varsayılan **90 gün** (`expires_at`), zorunlu rotate | süresiz makine anahtarı = sessiz kalıcı erişim |
| İptal SLA | revoke → **bir sonraki istek reddedilir** (otoriter/Redis, per-process cache'e bağlı değil) | uzun ömürlü token'da 60s cache penceresi kabul edilemez |

---

## 2. Tablo şeması — `api_tokens`

```
api_tokens
------------------------------------------------------------------------
id              uuid            PK, default gen_random_uuid()
tenant_id       uuid            NOT NULL, FK tenants(id) ON DELETE CASCADE
name            text            NOT NULL           -- insan-okur etiket ("asakai-prod")
token_hash      bytea/char(64)  NOT NULL, UNIQUE   -- HMAC-SHA256(pepper, plaintext)
prefix          text            NOT NULL           -- "imga_sk_live_" | "imga_sk_test_"
last4           char(4)         NOT NULL           -- UI önizleme (…AB12)
scopes          text[]          NOT NULL           -- {analyze:read, analyze:write, batch:submit, health:read}
created_by      uuid            NOT NULL, FK users(id)
created_at      timestamptz     NOT NULL, default now()
expires_at      timestamptz     NOT NULL, default now()+interval '90 days'  -- ölümsüz token YOK
last_used_at    timestamptz     NULL               -- debounce/async yazılır (§5)
revoked_at      timestamptz     NULL
revoke_reason   text            NULL
allowed_cidrs   inet[]          NULL               -- opsiyonel: AsakAI egress IP allowlist (§6)
------------------------------------------------------------------------
INDEX ix_api_tokens_token_hash ON (token_hash)     -- O(1) auth lookup
INDEX ix_api_tokens_tenant     ON (tenant_id)
CHECK (is_super_admin invariant DB'de değil, uygulama katmanında — bkz. §4)
```

**Önemli:** `token_hash` UNIQUE + indexli; auth sıcak yolu **tek** indeksli lookup.
Plaintext hiçbir zaman saklanmaz (yalnız create/rotate yanıtında bir kez döner).

---

## 3. RLS+FORCE politikası (migration 0006 deseni)

```sql
ALTER TABLE api_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_tokens FORCE ROW LEVEL SECURITY;

-- tenant-scoped okuma/yazma (imga_app)
CREATE POLICY api_tokens_tenant_isolation ON api_tokens
  USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

- CRUD uçları (`/tenants/me/api-tokens`) **`imga_app`** (RLS-bağlı) session ile çalışır.
- **Auth-time lookup istisnası (kritik — R2):** Gelen istekte henüz tenant bağlamı YOK;
  token'ın tenant'ı önce `imga_admin` (BYPASSRLS) bağlantısında `token_hash` ile çözülür.
  Çözüm biter bitmez **`imga_admin` bağlantısı BIRAKILIR** ve isteğin geri kalanı
  **`imga_app` ROLÜNE bağlı AYRI bir bağlantıda** çalışır; `app.current_tenant_id` o
  app-rol bağlantısında set edilir. Bu bir *rol devri*dir — yalnız GUC set etmek değil.
  Aksi halde (istek admin bağlantısında kalırsa) RLS bypass edilir ve izolasyon **sessizce
  hiç oluşmaz**. Test: `SELECT current_user` = `imga_app` doğrulanır (bkz. §9).

---

## 4. Auth katmanı — `get_current_user` çift-yol

Mevcut `get_current_user` yalnız JWT çözüyor. Yeni dal (sözde-akış):

```
Authorization: Bearer <credential>
  ├─ credential "imga_sk_" ile başlıyor mu?
  │    HAYIR → mevcut JWT yolu (değişmez)
  │    EVET  → API TOKEN yolu:
  │       1. prefix ortamı doğrula (live/test) — uyuşmazsa 401
  │       2. hash = HMAC-SHA256(pepper, credential)
  │       3. admin(BYPASSRLS) session: SELECT ... WHERE token_hash = hash
  │            - yok / revoked_at NOT NULL / (expires_at IS NULL OR expires_at <= now()) → 401 (otoriter, cache YOK)
  │       4. imga_admin bağlantısını BIRAK; kalanı imga_app ROLÜNE bağlı ayrı bağlantıda;
  │          o bağlantıda set_current_tenant(row.tenant_id)  ← RLS burada gerçekten bağlanır
  │       5. principal = ServiceAccount(tenant_id, scopes, token_id)
  │            - is_super_admin = False  (SERT invariant)
  │       6. last_used_at debounce güncelle (§5)
  └─ require_scope(...) ile endpoint yetkisi (require_role DEĞİL)
```

**Scope enforcement (R1 — fail-CLOSED, beyaz-liste):** `require_role` yerine
`require_scope("analyze:write")` dependency. İki **sert invariant** (kara-liste değil,
beyaz-liste):

1. **`require_role` bir `ServiceAccount` principal'ini KOŞULSUZ reddeder (403).** Makine
   token'ı hiçbir rol taşımaz; mevcut kullanıcı uçları (`require_role(tenant_admin/analyst/
   viewer)`) service_account'a **asla** açılamaz. (Rol maplemek = sızan token'la kurum ele
   geçirme.)
2. **Analiz/health dışı HER uç `require_scope` bildirmek ZORUNDA.** Scope bildirmeyen bir
   route otomatik **kapalıdır** (fail-closed) ve bir **test/lint** ile zorlanır (scope
   bildirmeyen + kullanıcı-auth'lu route eklenirse build fail). Yeni bir uç sessizce
   token'a açılamaz.

Sonuç: service_account token'ı **yalnız** `{analyze:read, analyze:write, batch:submit,
health:read}` scope'larının açtığı uçlara erişir; `api-tokens CRUD`, `users/invitations`,
`llm-credentials CRUD`, `tenant delete`, `settings`, `admin/*` **yapısal olarak** erişilemez.

**Scope seti (v1):**
| Scope | Uçlar |
|---|---|
| `analyze:read` | GET sonuç/health |
| `analyze:write` | POST /analyze/* (6 use-case) |
| `batch:submit` | (varsa) toplu ingest |
| `health:read` | GET /health, /health/ready |

---

## 5. `last_used_at` yazma-amplifikasyonu

Her AsakAI çağrısında satır UPDATE → yük altında write-amplification. **Karar:**
debounce — `last_used_at`'i yalnız son yazımdan **> 60s** geçtiyse güncelle (in-memory
son-yazım zaman damgası + best-effort async UPDATE). Auth doğruluğu `last_used_at`'e
bağlı DEĞİL; yalnız gözlem/anomali içindir. Revoke/expiry kontrolü her istekte otoriter.

---

## 6. Rotate / Revoke semantiği

- **Revoke:** `revoked_at = now()`, `revoke_reason`. `revoked_at`/`expires_at` kontrolü
  **her istekte otoriter** (indexli `token_hash` lookup) → bir sonraki istek 401.
  **Revoke/expiry yolunda cache YASAK** (tek doğruluk kaynağı). Performans gerekirse yalnız
  *pozitif* doğrulama (token var + aktif) çok-kısa cache'lenebilir, ama `revoked_at`/
  `expires_at` her istekte taze okunur — böylece "revoke → bir sonraki istek reddedilir"
  invariant'ı ihlal edilmez.
- **Rotate:** "iki-bağımsız-aktif-token" modeli — yeni token üret (create-once plaintext
  döner), AsakAI yeniye geçer, sonra eski **açıkça** revoke edilir. Otomatik grace
  window kullanılacaksa ≤ 24s ve eski token bireysel revoke edilebilir kalır.
- **Offboarding:** `created_by` kullanıcı deaktive edilirse onun mint ettiği token'lar
  otomatik revoke (veya sahiplik devri zorunlu) — sessiz kalıcı erişimi önler.
- **Opsiyonel IP-allowlist:** `allowed_cidrs` ile AsakAI egress IP'lerine bağla;
  beklenmeyen IP → reddet/alarm.

---

## 7. Denetim & sır hijyeni

- Token yaşam döngüsü (create/rotate/revoke) → mevcut `AuditService.log(...)` çağrısı;
  `details`'e **plaintext ASLA** yazma (yalnız `prefix`+`last4`).
- Her v1 çağrısı → `llm_call_audit` benzeri partner-audit satırı (request_id, token_id,
  tokens, success) — DPA denetim maddesi için (bkz. review §4A).
- Token yalnız `Authorization: Bearer`; **query-param olarak KABUL ETME**. Access log'da
  Authorization header'ı maskele.

---

## 8. Migration paketi (N+1'de üretilecek — kod DEĞİL, kapsam)

1. Alembic migration `00NN_api_tokens`: tablo + RLS+FORCE policy + indexler (0006 deseni).
2. `ApiTokenRecord` SQLAlchemy modeli (imga-db).
3. `ApiTokenService`: mint/verify (HMAC+pepper), lookup, last_used debounce, rotate/revoke.
4. `get_current_user` çift-yol + `require_scope` dependency + `ServiceAccount` principal.
5. Route'lar `/tenants/me/api-tokens` (create/list/rotate/revoke), TENANT_ADMIN-gated.
6. Env: `IMGA_APITOKEN_PEPPER` (per-env ayrı; asla paylaşılmaz).

---

## 9. Test matrisi (`:5433` canlı-Postgres — CLAUDE.md gereği)

| Test | Doğrulanan |
|---|---|
| RLS izolasyonu | Kurum A token'ı Kurum B verisini görmez/yazamaz |
| Auth çift-yol | `imga_sk_` → service_account; JWT → user (regresyon yok) |
| Scope enforcement | `analyze:write` token'ı user-mgmt/credentials/delete uçlarına 403 |
| RLS binding | Token yolu admin bağlantısında kalmıyor; sorgular `imga_app` rolünde (`SELECT current_user = imga_app`), RLS aktif |
| require_role reddi | `require_role`'lu bir uca service_account token'ı → **koşulsuz 403** |
| is_super_admin invariant | service_account asla super-admin bağlamına düşmez |
| Revoke SLA | revoke sonrası **bir sonraki** istek 401 (cache penceresi yok) |
| Expiry | `expires_at IS NULL` VEYA `<= now()` → 401 (ölümsüz token reddi) |
| Rotate | yeni token çalışır, eski revoke edilince reddedilir |
| Env-prefix | `imga_sk_test_` prod'da reddedilir |
| Sır hijyeni | plaintext yalnız create/rotate yanıtında; audit'te yok |
| (ops.) IP-allowlist | allowlist dışı IP reddedilir |

**Kickoff kabul kriteri:** RLS izolasyonu + revoke SLA + scope enforcement testleri yeşil.
