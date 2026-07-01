# `ApiTokenRecord` — Migration & Auth Tasarımı (design doc)

**Tarih:** 2026-07-01 · **Faz:** N+0 · **Statü:** TASARIM (kod değil)
**Amaç:** AsakAI ⇒ İmga v1 için kiracı-başına, uzun ömürlü, opak API token'ı.
**Şablon:** `packages/imga-api/.../routes/tenant_llm_credentials.py` + `TenantLlmCredential`
(create-once-plaintext, last4, RLS+FORCE, role-gated) — kanıtlanmış deseni klonla.
**RLS konvansiyonu referansı:** migration 0006 (`current_setting('app.current_tenant_id')::uuid`).

> Bu doküman N+1'de yazılacak Alembic migration'ı + auth katmanını **tanımlar**;
> kararlar [n0-response §1.4–1.6](2026-07-01-asakai-v1-n0-response.md) ile hizalıdır.
>
> **Kontrat hizalaması (2026-07-01, contract v1.1 §8):** önek `imga_live_`, scope
> **kaba** (`tenant` \| `service_account`), revoke SLA **≤60 sn** (§8.5). Bu üç nokta
> N+0 taslağını EZER; gövde buna göre güncellendi. Migration head **0031** → yeni **0032**.

---

## 1. Tasarım kararları (özet)

| Konu | Karar | Gerekçe |
|---|---|---|
| Token biçimi | **Opak** rastgele (`secrets.token_urlsafe`), DB'de hash'li | rotate/revoke için otoriter; stateless api-JWT iptal edilemez |
| Önek | `imga_live_` (contract §8) | staging öneki §8'de tanımsız — ayrı `imga_staging_` öneririm (staging↔prod karışması) |
| At-rest | **HMAC-SHA256(pepper)**, `hmac.compare_digest` | Argon2 auth sıcak-yolu için yavaş; HMAC sabit-zaman + O(1) lookup |
| Yetki | **kaba scope**: `tenant` (analyze+data) \| `service_account` (admin); `tenant_admin`/`analyst` DEĞİL | least-privilege; kiracı token'ı `/admin/*`'a erişemez |
| Kapsam | tenant-scoped, `is_super_admin=False` invariant | süper-admin token'ı üretilmesi imkânsız |
| TTL | varsayılan **90 gün** (`expires_at`), zorunlu rotate (≤1 yıl) | süresiz makine anahtarı = sessiz kalıcı erişim |
| İptal SLA | revoke → **≤60 sn** (contract §8.5); İmga ≤5s cache TTL ile daha sıkı | kontrat ≤60s ister; N+1 promptundaki "≤5s" ifadesi kontrata birebir değil |

---

## 2. Tablo şeması — `api_tokens`

```
api_tokens
------------------------------------------------------------------------
id              uuid            PK, default gen_random_uuid()
tenant_id       uuid            NOT NULL, FK tenants(id) ON DELETE CASCADE
name            text            NOT NULL           -- insan-okur etiket ("asakai-prod")
token_hash      bytea/char(64)  NOT NULL, UNIQUE   -- HMAC-SHA256(pepper, plaintext)
token_prefix    text            NOT NULL           -- "imga_live_" (public; §8) — staging öneki açık soru
last4           char(4)         NOT NULL           -- UI önizleme (…AB12)
scope           text            NOT NULL           -- 'tenant' | 'service_account' (kaba; contract §8)
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

**İlişkili (contract §9 — ayrı tablo, N+2):** `DELETE /v1/data/{session_id}` + 30-gün
retention için analyze istek/yanıtları `(tenant_id, session_id, created_at)` ile persist
edilmeli (ayrı `api_request_log` tablosu, RLS+FORCE). `api_tokens`'ın kapsamı değil ama
auth principal'i o log'a `tenant_id`+`session_id` sağlar — tasarım kararı şimdi, uygulama N+2.

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
  ├─ credential "imga_live_" (veya imga_staging_) ile başlıyor mu?
  │    HAYIR → mevcut JWT yolu (değişmez)
  │    EVET  → API TOKEN yolu:
  │       1. önek doğrula (imga_live_ / imga_staging_) — ortam uyuşmazsa 401
  │       2. hash = HMAC-SHA256(pepper, credential)
  │       3. admin(BYPASSRLS) session: SELECT ... WHERE token_hash = hash
  │            - yok / revoked_at NOT NULL / expires_at <= now() → 401 (≤5s cache TTL, §6)
  │       4. imga_admin bağlantısını BIRAK; kalanı imga_app ROLÜNE bağlı ayrı bağlantıda;
  │          o bağlantıda set_current_tenant(row.tenant_id)  ← RLS burada gerçekten bağlanır
  │       5. principal = ApiPrincipal(tenant_id, scope, token_id)   # scope: tenant | service_account
  │            - is_super_admin = False  (SERT invariant)
  │       6. last_used_at debounce güncelle (§5)
  └─ require_scope(...) ile endpoint yetkisi (require_role DEĞİL)
```

**Scope enforcement (R1 — fail-CLOSED, kaba scope):** iki scope —
`require_scope("tenant")` / `require_scope("service_account")`. Sert invariant'lar:

1. **`require_role` bir API-token principal'ini KOŞULSUZ reddeder (403).** API token'ı
   hiçbir kullanıcı-rolü taşımaz; mevcut kullanıcı uçları (`require_role(tenant_admin/
   analyst/viewer)`) API token'a **asla** açılamaz. (Rol maplemek = sızan token'la kurum
   ele geçirme.)
2. **`/admin/*` yalnız `service_account` scope; diğer her API-token ucu `tenant` scope
   ister.** Scope bildirmeyen bir route API-token'a **kapalıdır** (fail-closed), test/lint
   ile zorlanır. Yeni bir uç sessizce token'a açılamaz.

Sonuç: `tenant` scope'lu AsakAI token'ı yalnız `/v1/analyze/*` + `/v1/data/*` (kendi
tenant'ı) uçlarına erişir; `/admin/*`, kullanıcı-yönetimi, `llm-credentials`, `settings`
uçlarına **yapısal olarak** erişemez. `/admin/*` yalnız `service_account` (opsBearer).

**Scope seti (v1, kaba — contract §8):**
| Scope | Uçlar |
|---|---|
| `tenant` | `/v1/analyze/*` (6 use-case) + `/v1/data/*` (kendi tenant'ı) + `/health`, `/ready` |
| `service_account` | `/v1/admin/*` (kiracı & token yönetimi) |

---

## 5. `last_used_at` yazma-amplifikasyonu

Her AsakAI çağrısında satır UPDATE → yük altında write-amplification. **Karar:**
debounce — `last_used_at`'i yalnız son yazımdan **> 60s** geçtiyse güncelle (in-memory
son-yazım zaman damgası + best-effort async UPDATE). Auth doğruluğu `last_used_at`'e
bağlı DEĞİL; yalnız gözlem/anomali içindir. Revoke/expiry kontrolü her istekte otoriter.

---

## 6. Rotate / Revoke semantiği

- **Revoke (contract §8.5 = ≤60 sn):** `revoked_at = now()`, `revoke_reason`. Kontrat
  revoke'tan sonra ≤60 sn içinde 401 ister. İmga bunu **≤5 sn cache TTL** ile daha sıkı
  uygular: `token_hash` lookup pozitif sonucu ≤5s **Redis-paylaşımlı** cache'lenir; TTL
  dolunca DB'den taze okunur → sızan token en fazla ~5 sn yaşar (kontrat tavanının çok
  altında, tüm replikalarda tutarlı). *Not:* N+1 promptundaki "≤5s, contract §8" ifadesi
  kontratla birebir değil — §8.5 **≤60s** der; ≤5s bizim hedefimiz.
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
  `details`'e **plaintext ASLA** yazma (yalnız `token_prefix`+`last4`).
- Her v1 çağrısı → `llm_call_audit` benzeri partner-audit satırı (request_id, token_id,
  tokens, success) — DPA denetim maddesi için (bkz. review §4A).
- Token yalnız `Authorization: Bearer`; **query-param olarak KABUL ETME**. Access log'da
  Authorization header'ı maskele.

---

## 8. Migration paketi (N+1'de üretilecek — kod DEĞİL, kapsam)

1. Alembic migration `00NN_api_tokens`: tablo + RLS+FORCE policy + indexler (0006 deseni).
2. `ApiTokenRecord` SQLAlchemy modeli (imga-db).
3. `ApiTokenService`: mint/verify (HMAC+pepper), lookup, last_used debounce, rotate/revoke.
4. `get_current_user` çift-yol + `require_scope` dependency + `ApiPrincipal` (scope: tenant|service_account).
5. Route'lar `/v1/admin/tokens` (list/rotate/revoke) — `service_account` (opsBearer); tenant token erişemez. (Contract §8: token'lar admin console'dan mint edilir, self-service değil.)
6. Env: `IMGA_TOKEN_PEPPER` (32 byte, secret manager; per-env ayrı; asla repoya commit edilmez).

---

## 9. Test matrisi (`:5433` canlı-Postgres — CLAUDE.md gereği)

| Test | Doğrulanan |
|---|---|
| RLS izolasyonu | Kurum A token'ı Kurum B verisini görmez/yazamaz |
| Auth çift-yol | `imga_live_` → API token; JWT → kullanıcı (regresyon yok) |
| Scope enforcement | `tenant` scope token'ı `/admin/*` + user-mgmt/credentials uçlarına 403 |
| RLS binding | Token yolu admin bağlantısında kalmıyor; sorgular `imga_app` rolünde (`SELECT current_user = imga_app`), RLS aktif |
| require_role reddi | `require_role`'lu bir uca API token'ı → **koşulsuz 403** |
| is_super_admin invariant | API token asla super-admin bağlamına düşmez |
| Revoke SLA | revoke sonrası **≤5 sn** içinde 401 (contract §8.5 tavanı ≤60s) |
| Expiry | `expires_at <= now()` → 401 (`expires_at` NOT NULL) |
| Rotate | yeni token çalışır, eski revoke edilince reddedilir |
| Env-prefix | `imga_staging_` prod'da reddedilir |
| Sır hijyeni | plaintext yalnız create/rotate yanıtında; audit'te yok |
| (ops.) IP-allowlist | allowlist dışı IP reddedilir |

**Kickoff kabul kriteri:** RLS izolasyonu + revoke SLA + scope enforcement testleri yeşil.
