# Handoff: manual-ticket-promotion

**Tarih:** 2026-05-02 (local-agent)
**Sprint:** 8.3.1 follow-up (UX)
**Yazar:** local-agent
**Hedef:** server-agent
**Durum:** resolved
**Öncelik:** normal

## Bağlam

Browser smoke test sırasında tespit edilen UX eksiği: 3 SKIPPED_* kararında (manuel mod, eşik altı, belirsiz kategori) kullanıcı sistem güvenini override edip manuel olarak bilet açma yolu yoktu. Eski Streamlit'te de bu özellik yoktu, ama yeni multi-tenant sistem domain expert'lerinin override edebilmesini gerektiriyor.

## Talep

Backend endpoint + iki sayfada UI butonu lokalde shipped. Server agent `git pull` + redeploy yaparak browser smoke test'inin "yine de bilet aç" akışını doğrulasın.

## Mevcut durum — yapılanlar

**Backend** (`a8a4a32 feat(api): manual review-to-ticket promotion`):

- `ReviewService.promote_to_ticket` — `tenant_id` + `review_id` + `actor_user_id` alır, idempotent (`ReviewAlreadyTicketedError` → 409). RLS-bound app session içinde kategoriyi `_resolve_category_id` ile resolve eder, mevcut bridge'in `_split_title_summary` helper'ını reuse eder, `TicketService.create` ile manuel marker (`created_by_user_id != None`) bilet açar.
- `Review.decision` original kalır (audit trail); `Review.decision_reason = "manually_promoted_to_ticket"` analytics ayrımı için.
- Yeni audit action: `review.manual_ticket_creation` — `details` payload'unda `original_decision` alanı kullanım dağılımını ölçmek için.
- Yeni route: `POST /tenants/me/reviews/{review_id}/create-ticket` (201 / 404 / 409 / 403).
- Yeni guard: `_WriteMember` — viewer rolü hariç tutar.
- `test_review_manual_ticket.py` — 4 integration test (happy path + 409 idempotency + 403 viewer + 404 cross-tenant).

**Frontend** (`ea82902 feat(web): yine de bilet aç CTA on /analyze + /reviews/[id]`):

- `useManualPromoteReview` mutation hook (`use-reviews.ts`).
- `/analyze` decision card: ticket_id null AND decision ∈ {skipped_mode, skipped_threshold, skipped_belirsiz} ise "Yine de Bilet Aç" butonu, success'te card içinden ticket linkine geçer.
- `/reviews/[id]` detail page: aynı koşulla "Bu Analizi Bilete Dönüştür" butonu, success'te detail refetch.

## Yapılmayanlar (kabul edilebilir kapsam dışı)

- /reviews list sayfasında inline butonu yok — kullanıcı detail'e tıklayıp oradan promote eder. List'te chip count UX'i 8.3.4'te zaten polish edilecek.
- "Promotion sırasında ticket priority değiştir" UX yok — şu an default `NORMAL` ile açılır. Kullanıcı sonradan ticket detail'den priority değiştirebilir.

## Beklenen çıktı

- Server agent test stack'i koştursun: 33 → **37/37** (4 yeni test).
- Browser smoke: `/analyze` skipped_threshold yorumu → "Yine de Bilet Aç" → ticket açılır. `/reviews/[id]` aynı yol.

## İlgili dosyalar / commit'ler

- `packages/imga-api/src/imga_api/services/review_service.py` (promote_to_ticket + iki yeni exception)
- `packages/imga-api/src/imga_api/routes/tenant_reviews.py` (yeni POST endpoint)
- `packages/imga-api/tests/test_review_manual_ticket.py` (4 test)
- `packages/imga-web/src/hooks/use-reviews.ts` (yeni mutation)
- `packages/imga-web/src/app/(authenticated)/analyze/page.tsx` (decision card CTA)
- `packages/imga-web/src/app/(authenticated)/reviews/[id]/page.tsx` (detail CTA)

## Cevap

**Tamamlandı:** local-agent
**Commit'ler:**

- `a8a4a32` — `feat(api): manual review-to-ticket promotion`
- `ea82902` — `feat(web): yine de bilet aç CTA on /analyze + /reviews/[id]`

`ruff check src tests` clean, `mypy src` clean, `tsc --noEmit` clean.

---
