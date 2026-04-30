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

### A3. /analyze → auto-ticket bridge ✅ SHIPPED (Sprint 7.5.5 / Alt-Faz 3)

- **Durum**: ✅ Sprint 7.5.5 / Alt-Faz 3'te teslim edildi.
  - **Migration 0008**: `reviews` tablosu — text + text_hash (CHAR(64)), sentiment + categorization snapshot, automation_mode snapshot, decision enum, ticket_id FK (SET NULL), submitted_by_user_id, analyzed_at. RLS+FORCE policy. 4 index — tenant_id, partial composite (tenant + text_hash + analyzed_at) WHERE ticket_id IS NOT NULL, (tenant + analyzed_at DESC) for paging, ticket_id, deleted_at.
  - **`Review` modeli + `ReviewDecision` enum** (5 değer): `create`, `skipped_belirsiz`, `skipped_mode`, `skipped_threshold`, `skipped_dedup`.
  - **`review_text_hash` util** (`imga_core.text_utils`): `sha256_hex(normalize_turkish(text).strip())`. Sprint 6.10'daki `normalize_turkish` reuse — yeni Türkçe normalizasyon eklenmedi. Casing + outer-whitespace farkı dedup'ı bozmuyor.
  - **`ReviewService.record_and_decide`**: 5-branch karar ağacı sırayla (belirsiz → mode → threshold → dedup → create) — her branch ayrı bir decision_reason taşır. `automation_mode` review row'a snapshotlandı (TenantConfigService TTL cache okunuyor, live FK değil); böylece tenant mode'u sonradan flip etse de audit log'lar self-explanatory kalır.
  - **`POST /tenants/me/analyze`**: bearer + tenant-scoped + RLS-bound endpoint. Response: `{review_id, decision, decision_reason, ticket_id?, analyzed_at, analysis: AnalysisResult}`. Mevcut anonim `/analyze` SDK preview için olduğu gibi kalıyor.
  - **Dedup logic**: 24-saatlik pencere içinde aynı `text_hash` + non-null `ticket_id` varsa yeni review row yine yazılıyor (audit) ama `decision=skipped_dedup` + olan ticket'a pointer. Pencere dışında yeni ticket açılıyor (önceki muhtemelen kapanmış olabilir).
  - **Audit log**: Her analyze çağrısında `action="review.analyzed"` + `details={decision, review_id, ticket_id}` payload. Stable shape — log aggregation `details->>'decision'` ile gruplanabilir.
  - **Tests**: 10 yeni integration tests (`test_tenant_analyze.py`) — 5 decision branch × dedup TTL boundary (24h+1h yeni ticket) + casing/whitespace dedup invariance + audit log shape + RLS isolation iki tenant arasında. Plus 7 yeni `review_text_hash` unit tests (`test_text_utils.py`) — casing collapse, whitespace strip, sha256 spec match.
  - **decide_auto_create_state pure kaldı**: belirsiz branch ReviewService'te uygulanıyor (decide_auto_create_state mode + sentiment + confidence pure foksiyonu olarak duruyor). Daha temiz separation.
- **Bağımlılık**: ✅ kapandı.
- **Süre**: 1 gün (planlanan 1 gün, gerçekleşen 1 gün).
- **Frontend cleanup notu** (Sprint 7.7+): Mevcut anonim `/analyze` panel preview'i için kaldı; tenant context'i olan ekranlar (gelecek "Yorum Analiz Et" / batch ingestion UI) `POST /tenants/me/analyze` kullanmalı — ticket_id non-null dönerse "Bilet açıldı" toast'ı + ticket detail link, `skipped_*` dönerse ilgili sebebi (mod/eşik/belirsiz/dedup) inline gösterilmeli.

### A4. Comments + timeline integration ✅ SHIPPED (Sprint 7.5.5 / Alt-Faz 4)

- **Durum**: ✅ Sprint 7.5.5 / Alt-Faz 4'te teslim edildi.
  - **Migration 0009**: `ticket_comments` tablosu — author_user_id (SET NULL), body Text, kind VARCHAR(16), archived_by_user_id, deleted_at (archive flag). 3 CHECK constraint (kind enum, body length 1..8000), 3 index — composite (tenant + ticket + created_at) for timeline render, (tenant + author) for "my comments", deleted_at for archive sweep. RLS+FORCE policy.
  - **`TicketComment` modeli + `TicketCommentKind` StrEnum** (internal_note / customer_reply). `is_archived` + `archived_at` property accessors over `deleted_at`.
  - **Hard delete YOK, sadece archive**: deleted_at NOT NULL = archived. archived_by_user_id audit pointer. Timeline'da hâlâ görünüyor `is_archived: true` flag'iyle — historical record bozulamaz.
  - **`CommentService.create / list_for_ticket / archive`**:
    - **Role matrix** (Sprint 7.5 design review locked-in): VIEWER → only `internal_note`; ANALYST + TENANT_ADMIN → both kinds.
    - **State guard**: `customer_reply` forbidden when ticket is CLOSED / CANCELLED. `internal_note` state-orthogonal (allowed in every state, including terminals — post-mortem notes survive).
    - **Archive guard**: author OR TENANT_ADMIN; double-archive returns 409.
    - **Audit log**: `comment.create` + `comment.archive` actions, details payload includes ticket_id + kind/state at decision time.
  - **Routes** (4 yeni endpoint, hepsi /tickets prefix'i altında):
    - `POST /tickets/{id}/comments` — 201 body, role + state matrix enforced.
    - `GET /tickets/{id}/comments?include_archived=true` — chronological list, default includes archived rows.
    - `POST /tickets/{id}/comments/{cid}/archive` — soft-delete; 200 returns the archived comment view.
    - `GET /tickets/{id}/timeline` — polymorphic merged stream (state_transition + comment), sorted by occurred_at ASC. Eski `/transitions` endpoint backwards-compat için kaldı; yeni client'lar timeline'a geçmeli.
  - **Tests**: 16 yeni integration test (`test_comments.py`) — role matrix (viewer/analyst paths), state guard (CLOSED ticket internal_note allowed but customer_reply 403), archive (author + admin paths, non-author 403, double-archive 409), body length 8001 → 422, list include_archived toggle, /timeline merge order + archived events still surface, RLS isolation iki tenant ile, audit log shape, soft-delete persistence (row not physically deleted), state-orthogonality (internal_note for all 6 states via direct service call).
- **Bağımlılık**: ✅ kapandı.
- **Süre**: 1 gün (planlanan 1.5-2, tek günde shipped çünkü modeli + service + routes paralel yazıldı).
- **Frontend cleanup notu** (Sprint 7.7+): Ticket detail sayfasında ek bir "Comments" sekmesi açılmalı; üst kısmına `kind` switch (Internal Note / Customer Reply) + body textarea + send butonu. VIEWER rolünde Customer Reply seçeneği grayed-out. Timeline view'i `/tickets/{id}/transitions`'tan `/tickets/{id}/timeline`'a geçirilmeli — polymorphic event renderer (`type === 'comment'` ile `type === 'state_transition'` ayrı kart varyantları). Archived comment'ler yarı-saydam görünmeli + "kim arşivledi" hover tooltip'i.

### A5. Ticket aggregation + filter endpoints ✅ SHIPPED (Sprint 7.5.5 / Alt-Faz 2)

- **Durum**: ✅ Sprint 7.5.5 / Alt-Faz 2'de teslim edildi.
  - **Migration 0007**: `ix_tickets_tenant_state_priority` (composite), `ix_tickets_tenant_opened_at DESC` (composite), `ix_tickets_tenant_assignee` (partial index, `assigned_to_user_id IS NOT NULL`).
  - **TicketFilters Pydantic modeli** (`services/ticket_filters.py`): `state` / `priority` / `category_id` CSV multi-value (field_validator(mode="before") boş string'i `[]`'e çevirir, unknown enum 422), `opened_after` / `opened_before` ISO8601 datetime, `assignee` ∈ `me | unassigned | UUID`, `search` LIKE on title+summary, `order_by` Literal[opened_at, last_state_change_at, priority] + `order` Literal[asc, desc] (SQL injection imkansız), `limit` Field(ge=1, le=500), `offset` Field(ge=0).
  - **Service**: `TicketService.list_filtered` `(rows, total)` döner — total filtre sonrası pre-pagination. `TicketService.stats(group_by)` 4 axis (state/priority/category/assignee), kategoriler `LEFT JOIN categories` ile `label_tr` resolve eder.
  - **Routes**: `GET /tickets` artık tüm filtre setini accept ediyor + envelope `{tickets, total, limit, offset}` döner. Yeni `GET /tickets/stats` endpoint'i RLS-bound (aynı `app_session.begin()` + `bind_tenant` bloğu).
  - **EXPLAIN ANALYZE doğrulaması** (30k synth row üzerinde):
    - Q2 `tenant_id + opened_at >= cutoff + ORDER BY opened_at DESC LIMIT 100` → **Index Scan using ix_tickets_tenant_opened_at** ✅ (designed shape).
    - Q1 `tenant_id + state IN + priority IN + ORDER BY last_state_change_at DESC LIMIT 100` → planner `ix_tickets_last_state_change_at` (mevcut single-col) ile sorted-then-filter yapıyor; new composite index üretim ölçeğinde "filtre cardinality % 1'in altında" senaryosunda devreye girer (insurance index — şu anki distribution'da seçilmiyor ama varlığı doğru, kost azalınca planner geçer).
    - Q3 `tenant_id + assigned_to_user_id` → planner `ix_tickets_assigned_to_user_id` ile çalışıyor; partial composite multi-tenant ölçeğinde tenant_id'yi de leading-column olarak kullandığında devreye girecek.
  - **Tests**: 19 yeni test `test_ticket_filters.py`'de (CSV edge cases: empty / commas-only / multi-value / unknown enum, combined filters, search ILIKE, date range, limit le=500 enforcement, order_by injection guard, /stats 4 group_by axis, RLS isolation iki ayrı tenant ile, assignee="me" + "unassigned").
- **Frontend cleanup notları** (Sprint 7.7+'da `useTickets` hook'u backend'e push):
  - **Şu an client-side derive ediliyor** (Sprint 7.6.4 ticket list URL-bound filters): state filter localde array tutuluyor, fetch'te `?state=` tek-değerli olarak gönderiliyor. → Yeni endpoint'e CSV bind: `state.join(',')` URLSearchParam olarak.
  - **Dashboard 7.6.3 metric kartları**: full ticket fetch + JS reduce ile sayılıyor (Açık / Bugün / Yüksek / Son 7d). → `/tickets/stats?group_by=state` 4 kartı tek istekle besler. Trend chart için `?opened_after=` ile son 7 günü çekip group_by=state ile state breakdown gösterilebilir.
  - **Sayfalama**: artık `total` döndüğü için "X ticket / Y total" sayacı UI'a doğal eklenir. C5 cursor pagination'a kadar offset paging max 500'le sınırlı (zaten frontend default 25 kullanıyor).
  - **Backend filter pass-through alanları** (`useTickets` hook'unda exposed olmalı): `state[]`, `priority[]`, `category_id[]`, `opened_after`, `opened_before`, `assignee` (`"me"` / `"unassigned"` / userId), `search`, `order_by`, `order`. Default sort `last_state_change_at desc` zaten frontend default'uyla aynı.
- **Bağımlılık**: ✅ kapandı. C5 pagination'a kadar offset paging max 500.
- **Süre**: 1 gün (planlanan 0.5-1 gün, EXPLAIN doğrulaması + 19 test ile gerçekleşen).

### A7. Tenant directory ✅ SHIPPED (Sprint 7.5.5 / Alt-Faz 4)

- **Durum**: ✅ Sprint 7.5.5 / Alt-Faz 4'te teslim edildi.
  - **`UserService.list_for_tenant(tenant_id, search=None)`** — `User` ⨯ `UserTenantLink` JOIN, soft-deleted users excluded, opsiyonel case-insensitive ILIKE substring filter on email OR full_name. Returns frozen `TenantMember` dataclass list (user_id, email, full_name, role, is_active, last_login_at, invitation_accepted_at). Sorted by full_name ASC.
  - **`GET /tenants/me/users`** — `routes/tenant_directory.py`, ayrı router file (clean separation from tenant_config). Auth: TENANT_ADMIN / ANALYST / VIEWER (her tenant member okuyabilir — A7 spec). Query param: `search` (max 200 chars).
  - **OpenAPI tag**: yeni "Tenant Directory" tag (assignee picker / etc.).
  - **Tests**: 8 yeni integration test (`test_tenant_directory.py`) — 3 rol için read access, search by email substring, search by full_name (case-insensitive), no-match → empty, soft-deleted user hidden, RLS isolation iki tenant ile, last_login_at + invitation_accepted_at surface eden test.
- **Frontend cleanup notu** (Sprint 7.7+): Ticket detail "Atayı değiştir" dropdown'ı bu endpoint'i çağırmalı (`useTenantMembers()` hook). Mevcut "Sana / Atanmamış / Başka" placeholder kaldırılıp tam isim/email gösteren dropdown geliyor. Timeline'daki actor_user_id'ler de bu directory'yi cache'leyerek isim resolve etmeli (paralel fetch, prefetch'le shadcn dropdown'a feed).
- **Bağımlılık**: ✅ kapandı.
- **Süre**: 0.5 gün (planlanan 0.5).

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

## Frontend teknik notları (Sprint 7.7+ referansı)

### React 19 / Next 16 — `react-hooks/set-state-in-effect`

Next.js 16'nın varsayılan ESLint config'i `react-hooks/set-state-in-effect` kuralını **error** seviyesine çekti. Klasik "prop'tan state sync" patternini (useEffect içinde setState) ban'ladı, çünkü cascading re-render üretiyor:

```tsx
// ❌ Hatalı: React 19'da error
useEffect(() => {
  setSelected(prop);
}, [prop]);
```

Doğru pattern (React 19 docs): "previous prop tracking" — render içinde conditional setState. React bu özel durumda re-render'ı bail-out eder, ekstra cascade olmaz:

```tsx
// ✅ Doğru
const [selected, setSelected] = useState(prop);
const [lastProp, setLastProp] = useState(prop);
if (lastProp !== prop) {
  setLastProp(prop);
  setSelected(prop);
}
```

Sprint 7.6.5'te 3 component'te uygulandı (`automation-mode-form`, `category-toggle-list`, `custom-category-dialog`). Yeni form / sync-with-prop component yazılırken bu pattern kullanılmalı; aksi takdirde lint kuralı build'i kırar. Alternatif (state'i tamamen reset etmek istiyorsan): parent'ta `key={someValue}` ile component'i remount et.

### Diğer Next 16 davranış değişiklikleri

- **Turbopack default**: `next dev` ve `next build` Turbopack ile çalışır. Webpack'e dönmek için `--webpack` flag'i gerekir.
- **Async request APIs**: `params`, `searchParams`, `cookies()`, `headers()` artık Promise dönüyor — `await` zorunlu (zaten yeni kod awaited). Eski sync usage Sprint 16'da tamamen kaldırıldı.
- **Base UI primitives in shadcn**: shadcn/ui'nin yeni versiyonu Radix yerine `@base-ui/react` kullanıyor; trigger component'leri `asChild` yerine `render` prop'u alır:

  ```tsx
  // ❌ Eski Radix pattern
  <PopoverTrigger asChild><Button>...</Button></PopoverTrigger>
  // ✅ Base UI render prop
  <PopoverTrigger render={<Button>...</Button>} />
  ```

  TooltipTrigger button-only render eder (anchor wrap'lemiyor); link tooltip'leri için native `title` attribute kullan.
