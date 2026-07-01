> **TASLAK — HUKUKİ İNCELEME GEREKTİRİR.** Bu belge bir mühendislik ajanı
> tarafından, sistemin gerçek veri akışına dayanılarak hazırlanmış bir
> ilk-taslaktır; hukuki mütalaa değildir. İmzadan önce yetkin bir hukuk
> danışmanınca (KVKK + yurt dışı aktarım rejimi açısından) gözden geçirilmelidir.
> §7 uyarınca imza VDD tek sahibine aittir.

# Veri İşleme Sözleşmesi (DPA) — İmga ↔ AsakAI (VDD) · v1 partner API

**Sürüm:** taslak-0.1 · **Tarih:** 2026-07-01 · **Kontrat referansı:** İmga API v1.3
(`contract-v1.3-frozen`)

## 1. Taraflar ve roller

- **Veri Sorumlusu:** VDD Teknoloji (AsakAI ürününü işleten tüzel kişi). Nihai
  müşteri verisini toplar ve işleme amacını belirler.
- **Veri İşleyen:** İmga (bu kod tabanının sahibi tüzel kişi). Yalnızca Veri
  Sorumlusunun talimatıyla (v1 partner API çağrıları) veri işler.

Not: VDD ve İmga aynı sahiplik altında olsa da KVKK sorumlu/işleyen ayrımı
sözleşmeyle kurulur; bu belge o ayrımı belgeler.

## 2. İşlemenin konusu, süresi ve amacı

- **Konu:** AsakAI son-kullanıcılarının e-ticaret metinlerinin (yorum, destek
  talebi, iade/kargo bağlamı) yapay zekâ ile analizi.
- **Amaç:** Contract §4'teki 6 use-case (anomaly-explain, ticket-analyze,
  ticket-suggest-reply, return-analyze, cargo-optimize, free-analyze).
- **Süre:** Partner API entegrasyonu yürürlükte kaldığı sürece; fesihte §8.

## 3. Veri kategorileri ve veri sahipleri

- **Veri sahipleri:** AsakAI müşterilerinin son-kullanıcıları (tüketiciler).
- **Kategoriler:** Serbest-metin (yorum/talep içeriği) + iş bağlamı (KPI, iade
  listesi vb.). **İmga özel nitelikli veri talep etmez;** PII scrubbing best-effort
  AsakAI tarafındadır (contract §4 gereği İmga input reddetmez, filtrelemez).

## 4. Veri akışı ve saklama (sistemin gerçek davranışı)

- İstek gövdesi (prompt) İmga API'ye TLS üzerinden gelir → **Gemini'ye (Google)
  iletilir** (bkz. §5 alt-işleyen, yurt dışı aktarım).
- **İmga ham gövdeyi KALICI saklamaz.** `api_request_log` yalnızca şunları tutar:
  `context_sha256`, `response_sha256`, `response_summary` (≤200 karakter türetilmiş
  özet), token sayıları, `cost_try`, `use_case`, zaman damgası. Ham prompt/yanıt
  ve log'a/exporta yazılMAZ (yalnız hash + özet).
- **Saklama süresi:** türetilmiş kayıtlar **30 gün**; 30. günü aşanlar günlük bir
  arka plan job'uyla hard-delete edilir. Kanıt: `data_purge_audit` tablosu.

## 5. Alt-işleyenler (yurt dışı aktarım)

- **Google (Gemini API)** — model çıkarımı. Aktarım **yurt dışıdır** (contract
  v1.3 residency: tüm zone `outbound`). Bu aktarım için KVKK m.9 uygun aktarım
  şartlarının (açık rıza veya uygun güvence/taahhütname) AsakAI tarafında
  sağlanması Veri Sorumlusunun yükümlülüğündedir.
- İmga yeni bir alt-işleyen ekleyecekse Veri Sorumlusuna önceden bildirir.

## 6. Veri sahibi hakları (teknik olarak sağlanan)

- **Silme (KVKK m.7/m.11):** `DELETE /v1/data/{session_id}` → session'a bağlı tüm
  `api_request_log` satırları RLS-kapsamında silinir; kanıt `tenant_deletion_audit`.
  Silme sonrası aynı `session_id` → 404 `session_not_found`.
- **Erişim/taşınabilirlik (m.11):** `GET /v1/data/export` (NDJSON) → hash + özet +
  meta düzeyinde kayıtlar, ≤31 günlük pencere.

## 7. Teknik ve idari tedbirler

- Taşımada **TLS 1.3**; kimlik doğrulama **opak token + HMAC-SHA256(pepper)**
  (plaintext saklanmaz); çok-kiracılı izolasyon **PostgreSQL RLS + FORCE**.
- **Ham prompt/yanıt gövdesi log'lanmaz** (yalnız hash + ≤200 char özet).
- Secret'lar (token pepper, sağlayıcı anahtarı) repoya girmez; ayrı secret store.
- Token iptali: ≤60 sn yayılım (contract §8.5 MUST).

## 8. İhlal bildirimi, fesih ve iade/imha

- **İhlal bildirimi:** İmga, farkına vardığı bir veri ihlalini gecikmeksizin
  (ve mevzuatın öngördüğü sürede) Veri Sorumlusuna bildirir.
- **Fesih/imha:** Sözleşme sona erdiğinde İmga, kalan tüm türetilmiş kayıtları
  imha eder (30-gün retention job'u zaten sürekli imha uygular).

## 9. İmza

| Rol | Tüzel kişi | Ad-Soyad | İmza | Tarih |
|---|---|---|---|---|
| Veri Sorumlusu (VDD/AsakAI) | | | | |
| Veri İşleyen (İmga) | | | | |

---

**Açık uçlar (hukuk danışmanına):** (1) yurt dışı aktarım için AsakAI'nin
kullandığı hukuki dayanak (açık rıza mı, taahhütname mi) — bu belgeye referanslanmalı;
(2) saklama süresi 30 gün mevzuata/sözleşmelere uygun mu; (3) aynı-sahiplik altında
sorumlu/işleyen ayrımının biçimsel gereklilikleri.
