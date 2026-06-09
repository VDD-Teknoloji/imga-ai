# imga monorepo — tam kod incelemesi (2026-06-10)

Sprint 10.3 kapsamında çok-ajanlı inceleme: 6 paralel boyut
(API güvenlik, API doğruluk, worker/batch, web kalite, tasarım
uyumu, infra/test) + her critical/important bulgu için bağımsız
adversarial doğrulama ajanı. **47 ham bulgudan 17 yanlış-pozitif
doğrulamada elendi**; kalan 30 doğrulanmış + 16 minör bulgu
aşağıda. Bu oturumda kapatılanlar işaretli.

## Öncelikli backlog (önerilen sıra)

1. **X-Forwarded-For güvenilir-proxy allowlist** (critical) — login dışı IP-bazlı rate limitler spoof edilebilir; Sprint 8 TODO hiç yapılmamış.
2. **batch_analyzer hata yolları** (2 critical) — back-fill exception + record_and_decide rollback senaryoları; cancel→resume test kapsamı ile birlikte ele alınmalı.
3. **JWT_SECRET_KEY min-uzunluk doğrulaması** (5 satırlık fix, from_env).
4. **/tickets Suspense + Path B mirror** — AGENTS.md kuralına aykırı; reviews sayfası pattern alınarak hizalanmalı.
5. **Migration 0029 RLS eksiği** — invitations sütun migration'ı; tablo RLS'i 0028'de kuruluysa doğrula, değilse policy ekle.

## Critical — doğrulanmış

### [API Güvenlik + Multi-tenancy] X-Forwarded-For Header Spoofing in Client IP Extraction

`packages/imga-api/src/imga_api/routes/auth.py:554-560`

The _client_ip() function trusts X-Forwarded-For header without validating trusted proxies. While used primarily for audit logging (non-security-critical), an attacker behind a reverse proxy can spoof IP addresses. The function splits on the first comma and takes the leftmost IP, but without a trusted-proxy allowlist, any upstream client can set arbitrary values. Per the comment in rate_limit.py line 85-86, this was flagged as Sprint 8 TODO for implementation of trusted-proxy allowlist. In production deployments behind Caddy/nginx without explicit proxy configuration validation, this could byp…

### [Infra + Test Kalitesi] Missing test coverage for batch cancel→requeue→resume pipeline

`packages/imga-api/tests/test_batch_upload.py:459-525`

Test file has `test_cancel_before_worker_pickup_keeps_job_cancelled` and `test_cancel_terminal_job_returns_409` but no tests for the critical requeue path. The batch_service.py has a `requeue_job` method (line 310) that allows resuming FAILED/CANCELLED jobs from checkpoint, but no integration test validates: (a) cancelling a processing job, (b) requeuing it, (c) worker resuming from checkpoint without replaying completed rows. This edge case can cause duplicate reviews or missed rows in production.

### [Infra + Test Kalitesi] Auth tests verify refresh chain replay protection but lack forced-logout invalidation edge case

`packages/imga-api/tests/test_auth.py:284-365`

test_refresh_token_reuse_revokes_family verifies replayed tokens are rejected, and test_logout_revokes_family_and_subsequent_refresh_fails tests logout chain revocation. However, no test covers the race condition where: (1) user logs out, (2) another process simultaneously calls /auth/refresh with a stale token from before logout, (3) the outcome should be 401 (family already revoked) not 200 (token reissued). This edge case can leak sessions if family revocation check loses the race.

### [Tasarım Sistemi Uyumu] Multiple hardcoded blue chart colors bypass design tokens

`packages/imga-web/src/app/(authenticated)/insights/page.tsx`

Lines 624, 674, 803, 1014 use fill="#1e40af" (blue-900), line 921 uses stroke="#2563eb" (blue-600), line 963 uses fill="#0d9488" (teal-600). These are pre-Sprint 10.2 indigo/blue palette colors. Should use design tokens (--chart-1 for brand, --chart-2 for navy, or semantic color system via Tailwind).  
  ✅ **KAPATILDI:** insights NPS stroke -> var(--chart-1) (Sprint 10.3)

### [Tasarım Sistemi Uyumu] Line color palette hardcoded with old design colors

`packages/imga-web/src/app/(authenticated)/insights/_components/cohort-tab.tsx`

Lines 58-69 define LINE_COLOURS array with hardcoded hex values including #44557d (navy but not brand navy), #9333ea, #0891b2, #db2777, #65a30d, #7c3aed. First two colors (#e26622, #44557d) should anchor to design tokens (--brand and --navy), rest should align with chart palette strategy.  
  ✅ **KAPATILDI:** cohort paleti marka çiftiyle açılıyor; kalan 8 renk kategorik ayırt edilebilirlik paleti — bilinçli (Sprint 10.2/10.3)

### [Web Kod Kalitesi] CRITICAL: /tickets page missing Suspense wrapper + Path B mirror pattern

`packages/imga-web/src/app/(authenticated)/tickets/page.tsx:1-103`

AGENTS.md url-state-patterns.md audit table (line 159) explicitly flags /tickets as NOT having Suspense wrapper (❌) and NOT having Path B mirror pattern (❌). The page calls useTicketFilters() which uses useSearchParams() directly in the main component without Suspense boundary. This violates the mandatory rule from AGENTS.md: 'Every filter, tab, sort, paginator, search query, or date-range selection on a page MUST live in URL search params with a Suspense wrapper + Path B mirror pattern.' The audit notes user did NOT report bugs but 'F5 davranışı doğrulanmadı' (F5 behavior not validated). Requ…

### [Worker + Batch Pipeline] Unhandled exception in batch_job_id back-fill can cause silent chunk failure and partial progress corruption in parallel execution

`packages/imga-api/src/imga_api/workers/batch_analyzer.py`

Lines 983-987: The UPDATE statement to back-fill batch_job_id on auto-created reviews is not wrapped in try-except. If this UPDATE fails (e.g., constraint violation, concurrent delete), the entire app_session transaction rolls back, losing the review row AND any progress increments counted before the flush. In parallel chunk execution (Sprint 9.0.5-A), sibling chunks have already committed their progress to separate transactions, leaving the job in an inconsistent state (processed_rows incremented but the reviews missing). The batch worker will crash the job as failed, but partial progress fro…

### [Worker + Batch Pipeline] Potential data loss when record_and_decide fails mid-row and transaction rolls back

`packages/imga-api/src/imga_api/workers/batch_analyzer.py`

Line 971-980: The record_and_decide call is wrapped in try-except to log and skip the row on error. However, if the call partially succeeds (e.g., creates a review but fails on ticket creation), the entire transaction at line 799 will roll back, discarding all rows in the current chunk. The exception is logged but doesn't break the loop—instead, the row is marked as failed and the chunk continues. This creates a race: if a later row in the same chunk throws an unhandled exception (e.g., in the UPDATE statement or auditor path), the entire chunk transaction rolls back, making all succeeded rows…

## Important — doğrulanmış

### [API Doğruluk] N+1 query in _top_problems function

`packages/imga-api/src/imga_api/routes/tenant_executive.py`

The _top_problems helper performs a GROUP BY query to fetch top-N categories (line 273-294), then enters a loop (line 297+) that executes an additional query for each category to find the sample review text (lines 300-311). For a tenant with 10 negative categories shown, this becomes 1+N queries. Should pre-fetch all sample texts in a single WHERE IN query grouped by code, or use a LATERAL subquery to avoid the N additional roundtrips.  
  ⚖️ **BİLİNÇLİ KABUL:** kategori başına 1 örnek-yorum sorgusu, take=3 ile sınırlı (maks. 3 ek sorgu, indexli) — kabul edilen takas

### [API Doğruluk] Median calculation assumes non-empty sorted list without bounds check

`packages/imga-api/src/imga_api/services/analytics_service.py`

Line 645: median = hours_list[total // 2] is safe because line 637 guards total==0 with early return, but the integer division hours_list[total // 2] retrieves the middle element (or just-below-middle for even-length lists). This is correct for median but the code should document why floor division is intentional (not ceil).

### [API Doğruluk] Potential issue with median calculation in sensitivity_distribution

`packages/imga-api/src/imga_api/services/analytics_service.py`

Line 744: median = sorted_scores[total // 2] uses integer floor division. For a list of 3 elements (indices 0,1,2), total // 2 = 1 (correct middle). For a list of 2 elements (indices 0,1), total // 2 = 1 (the upper element, not lower). This gives upper-middle for even-length lists rather than lower-middle. Depends on the statistical definition intended; should document or use (total - 1) // 2 for consistency.

### [API Doğruluk] Index coverage gap: Review.sentiment_label + primary_category filter

`packages/imga-api/src/imga_api/routes/tenant_executive.py`

In _top_problems (line 288-289) and _voice_of_customer (line 365-367), queries filter on (Review.tenant_id, Review.sentiment_label, Review.primary_category). The Review model has tenant_id indexed but sentiment_label and primary_category filters are not covered by a composite index, forcing a table scan of all tenant's reviews before filtering. Consider adding an index on (tenant_id, sentiment_label, primary_category) or at least (tenant_id, sentiment_label) to accelerate executive dashboard queries.

### [API Güvenlik + Multi-tenancy] Login Rate Limit Bypass via Email Normalization

`packages/imga-api/src/imga_api/routes/auth.py:237-242`

Per-username rate limit uses str(body.email).lower() as the key (line 239). However, Unicode email addresses (IDN / internationalized domain names) may be normalized differently by different systems. An attacker could bypass the 10-calls/60s limit by using different Unicode representations of the same email (e.g., 'café@example.com' vs 'cafe@example.com'). While Python's str.lower() is deterministic within a process, no Unicode normalization (NFC/NFD) is applied, leaving potential for case-variation attacks on non-ASCII addresses.

### [API Güvenlik + Multi-tenancy] JWT Secret Key No Minimum Length Enforcement at Runtime

`packages/imga-api/src/imga_api/settings.py:186-192`

The JWT_SECRET_KEY defaults to 'change-this-in-production-min-32-chars' if not set in env (line 188). While this is clearly marked for change, no validation is performed to ensure the secret is at least 32 bytes when JWT_ALGORITHM=HS256. For HS256, the secret should be at least 32 bytes (256 bits). A misconfigured deployment with a short secret (e.g., 8 chars) would reduce key space to 64 bits. Recommendation: add validation in Settings.from_env() to reject secrets shorter than 32 bytes when HS256 is used.

### [API Güvenlik + Multi-tenancy] Cross-Tenant Admin Invitation Issuance Race Condition

`packages/imga-api/src/imga_api/routes/admin/invitations.py:38-48`

The _require_actor_can_manage() function allows super_admin to manage any tenant (line 42), but does not check if the tenant exists. A super-admin issuing an invitation to a non-existent tenant_id could store an invitation record pointing to a deleted tenant. While RLS policy would prevent acceptance (deleted tenants have deleted_at != NULL), this creates audit trail pollution and potential for confusion. The check should verify tenant.deleted_at IS NULL before allowing invitation creation.

### [Infra + Test Kalitesi] Dockerfile copies site-packages from builder but doesn't validate package integrity across layers

`packages/imga-api/Dockerfile:82`

Line 82 copies /usr/local/lib/python3.11/site-packages from the builder stage without checksums or layer caching invalidation strategy. If a dependency (torch, transformers, sqlalchemy) is patched in PyPI, a rebuild with the same imga-core/imga-db/imga-api versions will silently use the new patch-version package, bypassing pyproject.toml pin verification. Recommendation: add a COPY pyproject.lock step and validate checksums in the ONBUILD phase, or use poetry/pip-tools with locked versions.

### [Infra + Test Kalitesi] Migration 0029 has no RLS or FORCE ROW LEVEL SECURITY statements

`packages/imga-db/src/imga_db/alembic/versions/20260514_0000_0029_invitations_accepted_by_user_id.py`

Migration 0029 is a pure schema change (adds accepted_by_user_id column to invitations table) but contains no `ALTER TABLE invitations FORCE ROW LEVEL SECURITY` even though invitations table should remain tenant-isolated. While the table was created in an earlier migration with RLS enabled, a future accidental ALTER TABLE OWNER or migration that touches the column without repeating FORCE could weaken the policy. Consistency recommendation: add `ALTER TABLE invitations FORCE ROW LEVEL SECURITY` to 0029 to make tenant isolation explicit at every mutation point, matching the pattern in migrations…

### [Infra + Test Kalitesi] Local dev postgres healthcheck may not account for RLS policy initialization delay

`docker-compose.yml:30-34`

The postgres healthcheck in local docker-compose.yml (lines 30-34) checks `pg_isready` with 5s interval / 3s timeout / 5 retries = early success at ~15s. However, the post-startup initialization script (volumes line 27) runs SQL to create roles and set up RLS policies. If the `pg_isready` succeeds before the init script completes (especially with high concurrency from multiple containers starting), dependent services may connect before the imga_app and imga_admin roles are created, causing connection failures. Recommendation: add an explicit healthcheck that queries `SELECT 1 FROM information_…

### [Infra + Test Kalitesi] imga-core Dockerfile installs '[dev]' extras in builder but runtime stage copies no tests

`packages/imga-core/Dockerfile:29`

Builder stage (line 29) runs `pip install --no-cache-dir ".[dev]"` which includes dev dependencies (pytest, pytest-asyncio, etc.). Runtime stage (line 56) copies tests/ (line 51) but the image CMD is `pytest tests/ -v` (line 56). This works for imga-core local development but wastes ~300MB in the runtime image with pytest deps that production never uses. The imga-api Dockerfile avoids this by using a separate smoke-runtime stage. Recommendation: split imga-core into a runtime base + optional test layer, or use a tox/nox approach to test without baking pytest into the image.

### [Tasarım Sistemi Uyumu] Status/Priority badges use old Tailwind color classes (blue/amber/emerald)

`packages/imga-web/src/app/(authenticated)/action-items/page.tsx`

Lines 46-50 (STATUS_TONE) use border-blue-300/bg-blue-50/text-blue-800 for 'open', amber for 'in_progress', emerald for 'done'. Lines 53-55 (PRIORITY_TONE) use red-300/red-50/red-800 for high, amber for medium, emerald for low. These hardcoded colors don't use CSS tokens. Should migrate to semantic badge variants or design token colors.  
  ⚖️ **BİLİNÇLİ KABUL:** durum semantiği renkleri (mavi=devam ediyor, amber=uyarı) bilinçli — artık primary turuncu ile çakışmıyorlar

### [Tasarım Sistemi Uyumu] Alert severity badges hardcoded with old blue/amber/red Tailwind classes

`packages/imga-web/src/app/(authenticated)/trend-alerts/page.tsx`

Lines 30-32 (SEVERITY_TONE) define info='border-blue-300 bg-blue-50 text-blue-800', warning with amber, critical with red. These bypass design token system and create visual inconsistency with Sprint 10.2 palette.  
  ⚖️ **BİLİNÇLİ KABUL:** severity semantiği — bilinçli

### [Tasarım Sistemi Uyumu] SWOT recommendation tone colors use hardcoded Tailwind classes

`packages/imga-web/src/app/(authenticated)/strategy/page.tsx`

Lines 449-451 define SWOT priority tones (red-50, amber-50, emerald-50) for yüksek/orta/düşük. Lines 459-461 define SWOT type tones using emerald-50/red-50/blue-50. Line 260 hardcodes amber-50/amber-300 banner. Line 267 hardcodes text-amber-800.

### [Tasarım Sistemi Uyumu] Executive briefing uses hardcoded amber-50/amber-300 for banner and status badges

`packages/imga-web/src/app/(authenticated)/executive-briefing/page.tsx`

Line 148 uses bg-amber-50/border-amber-300, line 154 uses text-amber-800. Lines 408-410 define briefing status tones with emerald-50/red-50. These should use design token colors and semantic badge system.

### [Tasarım Sistemi Uyumu] Warning banner uses hardcoded amber colors

`packages/imga-web/src/app/(authenticated)/settings/integrations/page.tsx`

Line 275 uses border-amber-400 bg-amber-50 text-amber-700 for warning message. Should use semantic alert/banner system via design tokens.

### [Tasarım Sistemi Uyumu] Success message uses hardcoded emerald border and background

`packages/imga-web/src/app/(authenticated)/settings/users/page.tsx`

Line 201 uses border-emerald-300 bg-emerald-50 hardcoded. Also includes dark mode overrides (dark:border-emerald-900 dark:bg-emerald-950/30) suggesting this was token-unaware custom work.

### [Tasarım Sistemi Uyumu] Progress bar and status indicators use hardcoded emerald and amber colors

`packages/imga-web/src/app/(authenticated)/admin/llm-audit/page.tsx`

Line 152 uses bg-emerald-500 for progress fill. Lines 250-252 conditionally use amber-300 or emerald-300 borders for status indication. Should use design tokens.

### [Tasarım Sistemi Uyumu] Info banner uses hardcoded blue-50/blue-300/blue-800

`packages/imga-web/src/app/(authenticated)/settings/taxonomies/page.tsx`

Line 369 uses border-blue-300 bg-blue-50 text-blue-800 for instructional message. Should use design token colors.

### [Web Kod Kalitesi] Missing Suspense wrapper around useSearchParams-consuming component

`packages/imga-web/src/app/(authenticated)/tickets/page.tsx`

The /tickets page uses useTicketFilters() hook which calls useSearchParams() directly without a Suspense boundary. According to docs/agent-rules/url-state-patterns.md (audit table, line 159), the /tickets page is marked as NOT having Suspense wrapper and NOT following Path B mirror pattern. This can cause hydration race conditions on hard F5 refresh with non-empty query params, causing filter state to be lost. The audit notes that F5 behavior was not validated and Sprint 8.3.6 polish planned a refactor including useTicketFilters hook + Path B implementation.

### [Web Kod Kalitesi] sentiment_labels parameter consistency verified - correct Turkish label values

`packages/imga-web/src/hooks/use-reviews.ts:37-39`

Confirmed that sentiment_labels parameter accepts string[] and buildQueryString() correctly joins them with commas. Dashboard components (executive-hero.tsx:219, top-problems.tsx:75, attention-list.tsx:96, voice-of-customer.tsx:75) all correctly pass 'NEGATIF', 'POZITIF', 'NÖTR' (with Turkish dots preserved, no dotless I issues detected) matching backend expectation in tenant_reviews.py description 'CSV: NEGATIF,POZITIF,NÖTR'.  
  ✅ **KAPATILDI:** dashboard linklerindeki NEGATİF (noktalı İ) hatası NEGATIF olarak düzeltildi (Sprint 10.3)

### [Worker + Batch Pipeline] Redis SSE publish failures are silent and could leave frontend UI permanently stuck on progress page

`packages/imga-api/src/imga_api/workers/batch_analyzer.py`

Lines 1102-1111: The Redis publisher.publish() call is wrapped in a bare try-except that swallows all exceptions. If Redis is down and the batch completes successfully, _publish_terminal (lines 625-652) will fail silently, and the frontend SSE endpoint will never receive the terminal event. The client will remain subscribed indefinitely waiting for completion, even though the job succeeded on the backend. The progress GET endpoint remains functional as a fallback, but the real-time UI will hang.

## Minör bulgular

- **[API Güvenlik + Multi-tenancy]** Password Change Validation Uses Same-Second Window Edge Case (`packages/imga-api/src/imga_api/auth_deps.py:196-200`)
- **[API Güvenlik + Multi-tenancy]** X-Forwarded-For Trust Without Production Configuration Guidance (`packages/imga-api/src/imga_api/rate_limit.py:83-92`)
- **[API Güvenlik + Multi-tenancy]** Bearer Token Source Precedence Not Documented in Schema (`packages/imga-api/src/imga_api/routes/auth.py:144-146`)
- **[API Güvenlik + Multi-tenancy]** Generic Invitation Error Message Masks Valid Email-Exists Signal (`packages/imga-api/src/imga_api/routes/invitations.py:91-98`)
- **[API Güvenlik + Multi-tenancy]** Tenant Context Stashing on Request.state Not Validated in Routes (`packages/imga-api/src/imga_api/routes/auth.py:179-180`)
- **[API Doğruluk]** Optional coverage: avg_score rounding assumes non-null avg_score (`packages/imga-api/src/imga_api/services/analytics_service.py`)
- **[API Doğruluk]** Empty list slicing in compute_monthly_nps_trend (`packages/imga-api/src/imga_api/services/analytics_service.py`)
- **[API Doğruluk]** Empty list guard in _detect_text_column lacks explicit error message (`packages/imga-api/src/imga_api/services/trial_analysis_service.py`)
- **[Worker + Batch Pipeline]** GeminiKeyRotator.keys property returns a fresh list copy on every access, creating subtle bugs if callers assume identity (`packages/imga-core/src/imga_core/llm/key_rotation.py`)
- **[Web Kod Kalitesi]** Missing text overflow protection on customer quote (`packages/imga-web/src/components/dashboard/voice-of-customer.tsx:83`) — ✅ [overflow-wrap:anywhere] eklendi + backend URL temizliği (Sprint 10.3)
- **[Web Kod Kalitesi]** EventSource/AbortController cleanup is correct (`packages/imga-web/src/components/batch/BatchProgressStream.tsx:121-244`)
- **[Web Kod Kalitesi]** useEffect cleanup is correct with cancelled flag (`packages/imga-web/src/hooks/use-batch-uploads.ts:106-161`)
- **[Web Kod Kalitesi]** 401 retry logic race condition mitigated but verify mutation safety (`packages/imga-web/src/lib/api-client.ts:104-126`)
- **[Infra + Test Kalitesi]** RLS test for batch jobs only verifies 404 on cross-tenant list, not cross-tenant update/delete (`packages/imga-api/tests/test_batch_upload.py:534-570`)
- **[Infra + Test Kalitesi]** BERT model (~440MB) copied into runtime image on every build, no delta updates (`packages/imga-api/Dockerfile:82-86`)
- **[Infra + Test Kalitesi]** api-smoke service has no explicit restart policy; defaults to 'no' (correct but implicit) (`infra/imga/production/docker-compose.yml:268`)

## Yöntem notu

Her boyut bağımsız bir inceleme ajanı tarafından tarandı; critical/important bulgular
ikinci bir ajan tarafından "çürütmeye çalış" talimatıyla dosya-satır kanıtı üzerinden
doğrulandı. Kontrast/oran iddiaları gibi sayısal bulgular elle yeniden hesaplandı.
