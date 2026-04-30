# Post-Sprint-7 Roadmap

Sprint 7 sonu itibariyle backend konsolide ve canlıda çalışıyor: 6 alembic migration (RLS+FORCE protokollü), JWT-based auth (rotation chain compromise + password-changed-at access-token freshness), per-tenant tenant configuration (TTLCache + opt-in semantic), 6-state ticket lifecycle (state-machine + role matrix + per-tenant time windows), 114 test (E2E flow dahil) yeşil. 4 grup borç sırayla ele alınacak: **Grup A — Sprint 7.5.5** (frontend öncesi/paralel), **Grup B — API consistency** (Sprint 7.6 frontend'iyle birlikte), **Grup C — Sprint 8** (production), **Grup D — Sprint 8 sonrası** (acil değil ama açık). Toplam tahmini iş yükü: 8-15 gün, plus Grup D'nin opportunistic dağıtımı.

## Sprint 7 itibariyle ne shipped

| Kapsam | Durum |
|---|---|
| 3-rol DB infrastructure (owner/app/admin) + RLS+FORCE | ✅ |
| Auth + JWT + refresh chain + password-change invalidation | ✅ |
| Per-tenant taxonomy (categories + custom + automation_mode) | ✅ |
| Ticket model + lifecycle (6 state, 14 transition, role matrix) | ✅ |
| TicketService.find_due_* (auto-close worker primitives, pure SQL) | ✅ |
| /analyze pipeline (sentiment + categorization, BERT + override layers) | ✅ |
| 114 test: 41 SM unit, 13 ticket integration, 16 auth, 12 tenant config, vs. + 1 E2E | ✅ |
| OpenAPI docs (7 tag, 26/26 summary, 17 description, 7 örnek) | ✅ |

---

## Grup A — Sprint 7.5.5

**Kapsam**: Frontend (Sprint 7.6) yazılırken paralel ya da hemen sonra; MVP'ye gitmeden şart. Backend yüzeyinin tamamlanması.

**Tahmini süre**: 3-5 gün.

### A1. Admin tenant CRUD endpoints

- **Durum**: `TenantService.create / get / get_by_slug / update_settings` metodları yazılı, audit + soft-delete dahil. `require_super_admin` dependency hazır. HTTP yüzeyi yok — E2E test'te tenant'lar DB-fixture ile bypass'la oluşturuluyor.
- **Eksik**: `routes/admin/tenants.py` — `POST /admin/tenants` (create), `GET /admin/tenants` (list), `GET /admin/tenants/{id}`, `PATCH /admin/tenants/{id}` (settings + automation), `DELETE /admin/tenants/{id}` (soft). Hepsi `require_super_admin`.
- **Bağımlılık**: Yok.
- **Süre**: ~0.5 gün.

### A2. Invitation send + accept HTTP routes

- **Durum**: `InvitationService` (create, accept, revoke), `INVITATION_TTL`, token primitives (`generate_invitation_token` + sha256 hash), `invitations` tablosu + RLS (migration 0002), tüm servis testleri yazılı. HTTP route yok.
- **Eksik**: 
  - `POST /tenants/me/invitations` — TENANT_ADMIN davet gönderir; body `{email, role}`. E-mail teslimi şimdilik log-only (gerçek SMTP D7'de).
  - `POST /invitations/accept` — auth gerektirmez; body `{token, password, full_name}` (yeni kullanıcı için) veya `{token}` (mevcut kullanıcı için, JWT eklenir).
  - `GET /tenants/me/invitations` (TENANT_ADMIN için bekleyen davet listesi).
  - `DELETE /tenants/me/invitations/{id}` (revoke).
- **Bağımlılık**: D7 (mail server) ile birlikte düşün — şimdi log-only ile shipple, mail teslimi entegre edildiğinde davet teslim hattı çalışmaya başlar.
- **Süre**: ~0.5 gün.

### A3. /analyze → auto-ticket bridge

- **Durum**: `TicketService.create + decide_auto_create_state` (3 mod) + `find_open_for_review` (review_id dedup helper) hazır. `/analyze` endpoint salt sentiment+kategorizasyon döner; tenant context'i bile yok (anonim).
- **Eksik (4 tasarım kararı önce)**:
  1. **Authentication**: `/analyze` artık tenant-scoped mu olacak? (a) Bearer JWT zorunlu, tenant context JWT'den (b) `X-Tenant-Id` header (c) ayrı endpoint `/tenants/me/analyze`.
  2. **review_id**: (a) Caller verir + UUID validate edilir (b) Server üretir, response'a koyar (c) İdempotency key (`Idempotency-Key` header) → server hash'i review_id olarak kullanır.
  3. **Dedup**: aynı `review_id` için açık ticket varsa (`OPEN | IN_PROGRESS | PENDING_CUSTOMER | RESOLVED`) yeni yaratma; mevcut ticket'a referans ile dön. `find_open_for_review` zaten var.
  4. **Hata davranışı**: ticket create fail olursa (DB error, RLS reject, vs.) analiz sonucu yine 200 dönsün mü? Önerim: Evet, ticket create best-effort; response'a `ticket_id: null` + `ticket_create_error: "..."` koy. Kullanıcı analiz sonucunu kaybetmesin.
- **Bağımlılık**: 4 karar onayı.
- **Süre**: 1 gün (tasarım onayı sonrası impl + test).

### A4. Comments tablosu + endpoint + timeline integration

- **Durum**: 7.5 design review'da role matrisinde geçti ama tablo + endpoint deferral kararıyla ertelendi (kullanıcı: "VIEWER yorum: ✓ ama sadece internal note, customer-facing reply yasak"). Hiçbir kod yok.
- **Eksik**:
  - **Migration 0007**: `ticket_comments` (id, tenant_id, ticket_id, author_user_id, body, kind ∈ {internal_note, customer_reply}, created_at, updated_at, deleted_at) + RLS+FORCE + index.
  - **Model**: `TicketComment` + `TicketCommentKind` enum.
  - **CommentService**: `create` (role check: VIEWER yalnızca `internal_note`, ANALYST/ADMIN her ikisi), `list_for_ticket`, `soft_delete`. State'le orthogonal — comment her state'te eklenebilir, hatta CLOSED/CANCELLED'da bile (sadece `customer_reply` CLOSED/CANCELLED'da yasak).
  - **Routes**: `POST /tickets/{id}/comments` (body `{body, kind}`), `GET /tickets/{id}/comments`, `DELETE /tickets/{id}/comments/{cid}` (yazar veya admin).
  - **Timeline integration**: Mevcut `GET /tickets/{id}/transitions` yerine `GET /tickets/{id}/timeline` — events polymorphic: `state_transition` veya `comment`. Eski endpoint backwards-compat için kalabilir veya direkt rename.
- **Bağımlılık**: Yok.
- **Süre**: ~1.5-2 gün.

### A5. Ticket aggregation + filter endpoints (Sprint 7.6.3 dashboard tarafından açığa çıkardı)

- **Durum**: `GET /tickets` yalnızca tek-değerli `state` filtresi destekliyor; date-range, multi-state, priority filter, group-by aggregation yok. Dashboard 7.6.3 tüm metric'leri client-side derive etmek zorunda kaldı (full ticket fetch + JS reduce).
- **Eksik (öncelik sırası)**:
  - `GET /tickets/stats?period=today|7d|30d&group_by=state|category|priority` — dashboard kartları + chart için aggregator. Tek çağrıda count/sum döner, müşteri büyüdükçe N+1 fetch'i önler.
  - `GET /tickets` üzerinde `state` parametresinin multi-value alması (`?state=open&state=in_progress`) ya da `?states=open,in_progress,pending_customer` formatı.
  - `GET /tickets` üzerinde `opened_after`, `opened_before`, `closed_after`, `priority` filtreleri.
  - Cursor-based pagination (zaten C5 olarak listelendi; bu paragraf da onu çağırıyor).
- **Bağımlılık**: Yok. C5 pagination ile birlikte tek migration'da inebilir.
- **Süre**: ~0.5-1 gün (read-only stats endpoint, mevcut RLS'in altında basit aggregate sorgular).

### A6. Tenant-aggregate analysis metrics (SHI / kriz / kategori dağılımı)

- **Durum**: `POST /metrics` mevcut, ama stateless: çağıran taraf `AnalysisResult[]` gönderir, sonuç dönülür. Tenant'ın saklı analiz verisi için aggregate döndüren bir endpoint yok. Sebep: review tablosu + analize-arşivlemesi yok (Sprint 8 ingestion pipeline).
- **Eksik**:
  - Önce A3 (`/analyze → ticket bridge`) ya da paralel bir review storage tablosu lazım.
  - Sonra `GET /tenants/me/metrics?period=...` — SHI, crisis count, negative rate, top bottlenecks.
- **Bağımlılık**: A3 (analyze→ticket bridge) ya da bağımsız review storage.
- **Süre**: A3 ile birleşik 1 gün.
- **Etki**: Bu endpoint olana kadar dashboard'un SHI/kriz kartları "ticket-derived" alternatiflerle ikame edildi (Açık, Bugün Açılan, Yüksek Öncelik, Son 7 Gün Çözülen).

---

## Grup B — API Consistency (Sprint 7.6 frontend kararlarıyla birlikte)

**Kapsam**: Frontend yazarken "şu kalıp daha rahat" denilince refactor edilecek konvansiyon işleri. Tek bir doğru cevap yok; karar frontend ergonomisine göre verilir.

**Tahmini süre**: 1-2 gün.

### B1. Path style standardizasyonu (/admin/... namespace)

- **Durum**: 3 stil karışık:
  - `/auth/...` (auth, public-ish + bearer)
  - `/tenants/me/...` (active-tenant-scoped, tenant member-only)
  - `/tickets/...` (active-tenant-scoped ama top-level, /tenants/me prefix yok)
  - `/admin/...` namespace yok (super-admin endpoint'leri için)
- **Eksik**: Karar:
  - (a) Status quo: `/tickets` top-level kal; admin için `/admin/tenants`, `/admin/users` aç (A1+A2 ile gelir).
  - (b) Tutarlı tenant-scope: `/tickets` → `/tenants/me/tickets`, `/auth` ayrı kalsın.
  - **Önerim**: (a). `/tickets` top-level kalsın çünkü ticket = en sık kullanılan kaynak; URL kısa olsun. `/admin/...` namespace A1+A2 ile gelir.
- **Bağımlılık**: A1+A2 ile birlikte.
- **Süre**: 0 gün ekstra (A1+A2 ile gelir).

### B2. Response envelope kalıbı

- **Durum**: 3 farklı kalıp:
  - **Flat**: `TokenPairResponse` `{access_token, refresh_token, token_type}`, `TicketResponse`, `CategoryView`.
  - **Nested**: `MeResponse {user, active_context, available_tenants}`.
  - **Envelope**: `TicketListResponse {tickets: [...]}`, `TransitionsResponse {transitions: [...]}`, `CategoriesResponse {categories: [...]}`.
- **Eksik**: Tek standart belirle. Yaygın iki yaklaşım:
  - (a) **List = envelope**, **single = flat**. Pagination geldiğinde envelope'a `pagination: {next_cursor, has_more}` eklenir. (Mevcut tasarımla uyumlu.)
  - (b) **Her şey envelope**: `{data: ...}` her response'ta. Frontend için tek tip parse. Ama single-resource case'lerde gereksiz nesting.
  - **Önerim**: (a). Frontend kararı ama (a) JSON:API ve REST yaygın pratikleri ile uyumlu.
- **Bağımlılık**: Frontend tercihi (Sprint 7.6 başında karar).
- **Süre**: 0.5 gün (refactor + test güncellemesi).

### B3. Transition vocabulary kararı

- **Durum**: Server `to_state: TicketState` enum'u alıyor. E2E test helper'ı `"claim" → in_progress`, `"cancel" → cancelled+reason` çevirisini istemci tarafında yapıyor. Frontend de muhtemelen aynı çeviri.
- **Eksik**: Karar:
  - (a) **Status quo**: Server `to_state` REST-ful, frontend kendi action verb'ünü çevirir. Basit.
  - (b) **Action verb**: `POST /tickets/{id}/transitions {"action": "claim"}`. Daha okunabilir, ama server bilmediği action'larda 404 yerine 422 döner (ufak ergonomic kayıp).
  - (c) **Çift endpoint**: hem `/transition` (to_state) hem `/transitions` (action) tut. Esnek ama duplicate yüzey.
  - **Önerim**: (a). Çevriyi client tarafında bırak; helper kütüphaneleri (`@imga/sdk`) bu çeviriyi yapsın.
- **Bağımlılık**: Frontend tercihi.
- **Süre**: 0 gün eğer (a). 0.5 gün eğer (b). 1 gün eğer (c).

### B4. 204 + response_model=None idiomu DRY

- **Durum**: 5 endpoint'te tekrarlanıyor: `/auth/logout`, `/auth/change-password`, `/tenants/me/automation-mode`, `/tenants/me/categories/{id}`, `/tenants/me/custom-categories/{id}` (DELETE). Her birinde `status_code=204, response_model=None` çifti.
- **Eksik**: Custom decorator (`@no_content_route(...)` ya da `APIRoute` subclass'ı) bu 4 satırı 1'e indirir. Faydası kozmetik — kod 5 yerde, uzaklaştırınca okunurluk biraz düşer ama DRY artar.
- **Bağımlılık**: Yok.
- **Süre**: 2-4 saat. **İsteğe bağlı**.

---

## Grup C — Sprint 8 (production prep)

**Kapsam**: Production'a alınmadan önce şart olan operasyon altyapısı.

**Tahmini süre**: 3-5 gün.

### C1. Auto-close worker

- **Durum**: `TicketService.find_due_resolved` + `find_due_pending` pure SQL helper'ları hazır. `transition()` `actor_is_system=True` parametresini kabul ediyor (system-only PENDING_CUSTOMER → CLOSED transition'ı role matrisinde).
- **Eksik**: Scheduler seçimi:
  - (a) **APScheduler** FastAPI lifespan içinde: en kolay, ama API process'iyle bound — multi-instance scaling'de duplicate çalışır.
  - (b) **pg_cron** (postgres extension): postgres tetikler, ama uygulama mantığını SQL'e taşır (audit + state machine guard'ları PL/pgSQL'e çevirmek pahalı).
  - (c) **Ayrı worker container** docker-compose'a: aynı kod, periodic task. Production'da scaling'le iyi anlaşır.
  - **Önerim**: (c). Production'da API replicas çoğalsa worker tekil kalır; lock ihtiyacı yok.
- **Bağımlılık**: Yok (hepsi kod-içi karar).
- **Süre**: 1-1.5 gün.

### C2. Backup stratejisi

- **Durum**: Hiç yok. Production veriyi kaybetme riski.
- **Eksik**:
  - Daily `pg_dump` (ayrı container, cron-style)
  - Encrypted upload to S3 ya da Hetzner Storage Box
  - Retention: 7 daily, 4 weekly, 12 monthly
  - Restore prosedürü dokümante (operations runbook'u)
- **Bağımlılık**: AWS hesabı (Teknopark kredisi) ya da Hetzner Storage Box.
- **Süre**: 0.5-1 gün.
- **Önemli**: İlk müşteri verisinden ÖNCE yapılmalı.

### C3. Production deploy

- **Durum**: docker-compose dev için var. Production yapılandırması yok.
- **Eksik**:
  - Hetzner CPX41 (kullanıcı tarafından seçildi) provisioning
  - Caddy reverse proxy + otomatik TLS
  - Cloudflare DNS (app.imga.ai, api.imga.ai, staging.imga.ai)
  - Production .env (root-only, /etc/imga/production.env)
  - GitHub Actions CI/CD: push → SSH deploy
- **Bağımlılık**: Domain ownership, Hetzner hesabı, Cloudflare hesabı.
- **Süre**: 1-2 gün.

### C4. Monitoring + Alerting

- **Durum**: Hiç yok.
- **Eksik**:
  - Uptime Robot ücretsiz tier (50 monitor, /health probe)
  - Sentry ücretsiz tier (FastAPI integration, error capture)
  - Log aggregation: başlangıçta `docker compose logs`, sonra Loki + Grafana (Sprint 9+)
- **Bağımlılık**: Hesap açma.
- **Süre**: 0.5 gün.

### C5. Pagination

- **Durum**: `GET /tickets`, `GET /tenants/me/categories`, `GET /tickets/{id}/transitions` tüm row'ları döner. Liste büyürse memory + transfer pahalanır, frontend yavaşlar.
- **Eksik**: Cursor-based pagination (offset DB seviyesinde stable değil; INSERT/DELETE listenin ortasında shift'e neden olur).
  - Query params: `?limit=50&after=<cursor>`
  - Response envelope: `{tickets: [...], next_cursor: "...", has_more: true}`
  - Cursor encoding: `(last_state_change_at, id)` tuple base64'lenir; sıralama deterministik tie-break ile.
- **Bağımlılık**: B2 envelope kararı (envelope'a pagination alanı ekleyeceğiz).
- **Süre**: 0.5-1 gün.

---

## Grup D — Sprint 8 sonrası (acil değil ama açık)

**Kapsam**: MVP çalıştıktan sonra opportunistic dağıtılır. Sırayla bağımlı değil; her biri bağımsız.

### D1. Out-of-window reopen → linked ticket

- **Durum**: `parent_ticket_id` kolonu migration 0006'da hazır. `ticket_reopen_window_days` (default 30) tenant config'de.
- **Eksik**: 30+ gün geçmiş CLOSED/CANCELLED ticket'ı reopen etmek isterken `WindowExpiredError` alan kullanıcıya `POST /tickets/{old_id}/relink` (TENANT_ADMIN-only): yeni ticket aç, `parent_ticket_id = old_id`, başlık + summary copy. Tarihçe iki ticket arasında köprü olur.
- **Bağımlılık**: Yok.
- **Süre**: 0.5 gün.

### D2. Customer-inbound webhook bridge

- **Durum**: `TicketService.record_customer_inbound` metodu + `POST /tickets/{id}/customer-inbound` endpoint hazır. Webhook tetikleyici yok.
- **Eksik**: HMAC-signed webhook endpoint (`POST /webhooks/customer-inbound`) → record_customer_inbound çağrısı. Twitter/email/SMS gibi kanallardan tetiklenecek.
- **Bağımlılık**: D8 Twitter botu kodu veya başka inbound kanal.
- **Süre**: 0.5 gün.

### D3. Redis cache migration

- **Durum**: `TenantConfigService` `cachetools.TTLCache` (in-memory, 5 dk TTL, lifespan-owned) kullanıyor. Multi-instance scaling'de paylaşılmalı (her instance kendi cache'iyle çalışırsa stale farklılık olur).
- **Eksik**: cachetools.TTLCache → Redis arka uçlu wrapper (aynı `__getitem__`/`__setitem__`/`pop` interface'i). `app.state.tenant_config_cache` yer değiştirir, `get_tenant_config_cache` aynı kalır.
- **Bağımlılık**: Redis container (docker-compose'a ekle), production'da managed Redis instance.
- **Süre**: 0.5-1 gün.

### D4. BERT cache build-time embed kontrolü

- **Durum**: Sprint 6.11'de eklenmişti. Mevcut branch'te hâlâ aktif mi kontrol edilmeli.
- **Eksik**: Dockerfile'da BERT model dosyalarını build-time'da çekilip image'a embed edilmesi. Cold start <3s vs ~20s.
- **Bağımlılık**: Yok.
- **Süre**: 1-2 saat (kontrol + gerekirse re-add).

### D5. Gemini API key aktivasyonu (LLM fallback)

- **Durum**: `HybridClassifier` + `create_llm_provider` + `IMGA_LLM_FALLBACK_ENABLED` env hazır. Gemini API key yok.
- **Eksik**: Ücretsiz tier key alma, `.env`'e ekleme, `IMGA_LLM_FALLBACK_ENABLED=true`. Düşük confidence sınıflandırmalar için LLM fallback aktif olur.
- **Bağımlılık**: Google Cloud hesabı.
- **Süre**: 30 dk.

### D6. google-generativeai → google-genai SDK migration

- **Durum**: Mevcut `google-generativeai` paketi FutureWarning veriyor (Google yeni `google-genai`'ye geçiyor).
- **Eksik**: SDK swap, provider class API uyumu.
- **Bağımlılık**: D5 sonrası daha mantıklı (SDK kullanılınca migration ihtiyacı netleşir).
- **Süre**: 1-2 saat.
- **Aciliyet**: Düşük (mevcut paket çalışıyor, sadece warning).

### D7. Mail server / SES entegrasyonu

- **Durum**: Davet email'i şu an log'a yazılıyor (gerçek SMTP yok). A2'deki invitation send route bu yokluğa toleranslı yazılacak.
- **Eksik**: SMTP entegrasyonu — Mailcow self-host (önceki konuşma) veya AWS SES.
- **Bağımlılık**: A2 invitation flow (D7 olmadan davet teslim edilmiyor — ama route shippable).
- **Süre**: 1 gün.

### D8. Twitter botu entegrasyonu

- **Durum**: Kod henüz teslim edilmedi (kullanıcı notu).
- **Eksik**: Code review + analiz (Sprint 0 tarzı sıfır-temizlik) + entegrasyon (D2 webhook bridge ile).
- **Bağımlılık**: Kod teslimi.
- **Süre**: ?? (kod görmeden tahmin yok).

---

## Bağımlılık özet diagramı

```
A1 (admin tenant CRUD) ─┬─▶ A2 (invitations)
                        │
A3 (analyze→ticket) ────┘  (decision-only dep)

C2 (backup) ───▶ C3 (deploy) ───▶ C4 (monitoring)

D2 (webhook) ───▶ D8 (Twitter botu)
A2 ───▶ D7 (mail server) → A2 davet teslim aktive olur
B1 (path standardization) ←─┐ A1+A2 ile birlikte gelir
B2 (envelope) ←─────────────┤ frontend tercihi (Sprint 7.6)
B3 (action verb) ←──────────┤ frontend tercihi
                             │
C5 (pagination) ───▶ B2'ye dependent
```

## Önerilen sıra

1. **Sprint 7.6** (frontend) ile paralel: **A1, A2, A4** (admin tenant CRUD, invitation routes, comments). Frontend ekibi bu üç parçayı kullanan UI yazarken backend ekibi A3'ün tasarım kararlarını çözer.
2. **A3** (analyze→ticket bridge) — 4 tasarım kararı onaylanınca impl + test.
3. **B1, B2, B3** — frontend ergonomy feedback'iyle birlikte refactor (Sprint 7.6 sonu).
4. **Sprint 8**: C2 (backup) → C3 (deploy) → C4 (monitoring) → C1 (auto-close worker) → C5 (pagination).
5. **Sprint 9+**: D'den sırayla, en gerekenden başlayarak (D5 + D2 erken; D8 kod gelince; D3 Redis multi-instance scaling olunca).
