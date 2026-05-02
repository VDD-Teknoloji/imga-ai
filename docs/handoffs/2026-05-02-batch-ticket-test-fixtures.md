# Handoff: batch-ticket-test-fixtures

**Tarih:** 2026-05-02 (local-agent)
**Sprint:** 8.3.1 → 8.3.2 köprü
**Yazar:** local-agent
**Hedef:** server-agent
**Durum:** resolved
**Öncelik:** yüksek

## Bağlam

Round-2 asyncpg fix sonrası test stack 32/35'e (3 fail) ve manual_ticket dosyası test compose listesinde olmadığı için 4 test eksik koşuyordu. Production smoke test başarılı (gerçek ticket'lar yaratıldı), yani üretim kodu sağlam — sorun yalnızca test fixture setup'ında idi.

## Talep

Lokalde 3 fail'in kök nedeni teşhis edildi + düzeltildi + test compose genişletildi. Server agent `git pull` çekip test stack'i koştursun, **37/37 pass** beklenir.

## Mevcut durum

Yapılanlar:

### Tanı

3 fail'in tek kök nedeni: **stub pipeline'ın confidence çıktısı semi_auto eşik altında kalıyordu**.

- `decide_auto_create_state` (services/ticket_service.py:116-140) semi_auto'da iki şart arar: `confidence > 0.7` AND `sentiment_score < -0.5`.
- `KeywordCategoryClassifier` confidence'ı `min(1.0, hit_count / CATEGORY_NORMALIZATION_DIVISOR)` formülünden gelir; divisor = 5.0 (config.py:95). Yani **eşik için en az 4 kategori keyword hit'i** lazım (4/5 = 0.8).
- 3 fail eden test'in text'i: `"kargom kötü ve 5 gündür gelmedi"` veya `"kargom kötü ve gelmedi"`. KARGO_KEYWORDS lexicon'unda eşleşen substring sayısı yalnızca 2 (`kargo`, `gelmedi`) → 0.4 confidence → eşik aşılmıyor → bridge `SKIPPED_THRESHOLD` döndürüyor → `tickets_created == 0`.
- Sentiment yönü doğruydu (`gelmedi` + `kötü` stub'da NEGATIF -0.85, < -0.5 ✓), sorun confidence katmanındaydı.

### Production etkisi: SIFIR

Browser smoke test başarılı çünkü prod'da BERT analizine ek olarak HybridClassifier (LLM fallback) çalışır ve gerçek müşteri yorumları zaten çoklu kategori kelimesi içerir. Test stub'ı yalnızca KeywordCategoryClassifier kullanıyor; eşik için yeterli yoğunluk yok.

### Fix

3 testin text'ini KARGO_KEYWORDS lexicon'undan **7+ keyword içeren** bir cümle ile değiştirdim:

```text
"kargom kargocu gelmedi, teslimat ulaşmadı, takip kodu yanlış, çok kötü hizmet"
```

Hit'ler: `kargo`, `kargocu`, `kargocu gelmedi`, `gelmedi`, `teslimat`, `ulaşmadı`, `takip kodu` → 7 hit → confidence = 1.0 ≥ 0.7 ✓. Stub sentiment: `gelmedi` + `kötü` → NEGATIF -0.85 < -0.5 ✓.

### Test compose'a manual_ticket eklendi

`infra/imga/test/docker-compose.yml` pytest komutuna `tests/test_review_manual_ticket.py` satırı eklendi. Önceki 32 test → 37 test (32 + 5 = 4 manual_ticket + 1 yeni intra-batch dedup automation_mode regression).

## Beklenen çıktı

`origin/main` üzerinde tek commit: `fix(test): batch ticket creation fixtures align with semi_auto threshold + manual_ticket in compose`

Server agent test stack'i koştursun, beklenen `37/37 passed`.

## İlgili dosyalar / commit'ler

- `packages/imga-api/tests/test_batch_upload.py` — `test_auto_create_enabled_in_semi_auto_creates_tickets_for_negatives` text güncellemesi
- `packages/imga-api/tests/test_batch_dedup.py` — `repeat_text` (iki yerde aynı string)
- `infra/imga/test/docker-compose.yml` — pytest komutuna `test_review_manual_ticket.py`
- `packages/imga-api/src/imga_api/services/ticket_service.py:116-140` — `decide_auto_create_state` (üretim kodu, dokunulmadı)
- `packages/imga-core/src/imga_core/classifiers/keyword.py:65-87` — confidence formula (üretim kodu, dokunulmadı)

## Cevap

**Tamamlandı:** 2026-05-02 (local-agent)
**Commit:** `132512f` — `fix(test): batch ticket fixtures meet semi_auto confidence threshold`
**Patch (server):** `/tmp/batch-ticket-fixtures-fix.patch` (110 satır)

Beklenti: `37/37 passed` server-side. Failure pattern eski (asyncpg shared session veya loop kirliliği) değildi; tamamen test-side fixture-eşik uyumsuzluğu.

---
