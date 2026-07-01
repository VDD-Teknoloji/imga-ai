# AsakAI → İmga v1 API — Kickoff Hazırlık İncelemesi

**Kimden:** İmga Backend (kod tabanı incelemesi) · **Kime:** AsakAI Ekibi / VDD Tech
**Tarih:** 2026-07-01 · **Durum:** Sprint 13 kickoff ÖNCESİ teknik değerlendirme
**Kaynak:** *İmga → AsakAI Entegrasyon Brifi (v1)* + `imga-ai` kod tabanı taraması
**Yöntem:** 9 yetenek alanı kod-envanteri + boşluk analizi + 5 adversaryal risk merceği
(çok-ajanlı tarama); kritik iddialar birincil kaynaktan (grep/read) ayrıca doğrulandı.

> **Kapsam notu:** Bu bir **teknik fizibilite ve kontrat-flag** dokümanıdır. Hiçbir
> DPA/yasal taahhüt, dış gönderim veya kod değişikliği içermez. Brief §8'in
> *"kontrat üstünde tartışılacak noktaları kickoff'tan önce flag'leyin"* çağrısına
> yanıttır.

---

## 0. Yönetici Özeti (TL;DR)

**İyi haber:** İmga'nın mevcut altyapısı bu entegrasyonun **büyük kısmını taşıyacak
olgunlukta** — çok-kiracılı RLS, JWT auth + refresh rotation, tenant-başına şifreli
LLM kimlik bilgileri (`tenant_llm_credentials`), Gemini anahtar rotasyonu, prompt
şablon kayıt sistemi, LLM çağrı denetimi (`llm_call_audit`) ve batch SSE iskeleti
zaten var. 6 use-case'in ikisi (`free-analyze`, `ticket-analyze`) mevcut uçların
üzerine ince bir *cephe (facade)* ile karşılanabilir. **Mühendislik kapasitesi
sorun değil.**

**Kötü haber — kod yazımına BAŞLAMADAN çözülmesi gereken 3 blokaj var:**

| # | Blokaj | Neden kritik | Kimin kararı |
|---|---|---|---|
| B1 | **Veri ikametgahı ↔ yurt dışı LLM çelişkisi** | Brief "TR'de veri ikametgahı ZORUNLU, AB bile kabul değil" diyor; ama Gemini/OpenAI/Anthropic inference'i TR dışında yapılır ve Google'ın **TR bölgesi yoktur**. Bu bir mühendislik görevi değil, **tedarikçi-seviyesi imkânsızlık**. | VDD hukuk + strateji |
| B2 | **Kontrat dokümanı elde yok** | `docs/imga-api-v1-contract.md` İmga reposunda **yok** (doğrulandı). Request envelope (§2), hata şeması, `use_case` tanımlayıcı, versiyon politikası tanımsız → başarı kriteri yazılamaz. | AsakAI teslim eder |
| B3 | **Entegrasyon yönü çelişkili** | Brief hem "AsakAI, İmga'yı çağırır" (kiracı token + SSE) hem "İmga, AsakAI'yı LLM backend olarak çağırır" (çok-sağlayıcı router) kurgusunu içeriyor. İkisi zıt yön; ikisi birden v1'deyse iş ikiye katlanır. | AsakAI + İmga |

**Karar:** Kickoff'u **kod yazımıyla değil, ~1 haftalık bir "kontrat-dondurma"
(contract-freeze) fazıyla** başlatmayı öneriyoruz. Aşağıdaki §1 sorularının kararı,
DTO'lar ve `/v1` OpenAPI yüzeyi netleşmeden N+1'in başarı kriteri tanımlanamaz.

**Zaman gerçekçiliği:** 8 boşluk alanının ~7'si bağımsız olarak **"L" (large)**.
Kaba tahmin **12–16 mühendis-haftası**; brief'in 6 hafta × 2 mühendis planı (≈12
mühendis-haftası) frontend, migration ritüeli, `:5433` canlı-Postgres test vergisi
ve koordinasyonu **saymıyor**. Mevcut kapsam 6 haftaya sığmaz — §5'te yeniden
sıralama öneriyoruz.

---

## 1. Kickoff'tan ÖNCE Karara Bağlanacak Sorular (contract-freeze girdi listesi)

Bunlar brief'in ~40 açık sorusunun deduplike + önceliklendirilmiş halidir. Her biri
en az bir tasarımı kökten değiştirir; cevaplanmadan ilgili kalem başlatılamaz.

### Sözleşme & yön (en yüksek öncelik)
1. **Entegrasyon yönü:** AsakAI İmga'nın *tüketicisi* mi, İmga'nın çağırdığı bir
   *LLM backend* mi, yoksa *çift yönlü* mü? → **Öneri:** v1 için yalnız "AsakAI
   tüketici" yönünü sabitle; AsakAI-as-backend router işini (≈2 hafta) v1'den çıkar.
2. **Kontrat dokümanı:** `docs/imga-api-v1-contract.md`'nin tam metni (§2 request
   envelope, hata şeması, `use_case` enum, versiyon politikası) repoya alınmalı. →
   FastAPI'nin `/openapi.json`'ı ile karşılaştırılacak **altın-snapshot** haline gelecek.
3. **Domain:** Canonical domain `api.imga.ai` mi `api.imga.tech` mi? (Repo baştan
   sona `.ai`; `.tech` **hiç geçmiyor** — doğrulandı.) `.tech` kullanılacaksa DNS +
   Caddy `conf.d` + `IMGA_COOKIE_DOMAIN` + CORS aynı PR'da güncellenmeli.

### Kimlik & yetki
4. **API token modeli:** Opak, DB'de hash'li (kolay iptal) mi, yoksa stateless
   imzalı api-JWT mi? → **Öneri:** opak + DB-backed (rotate/revoke için şart),
   `imga_sk_live_` / `imga_sk_test_` ortam-önekli, per-env ayrı pepper.
5. **Token scope/rol:** Makine token'ı hangi yetkiyi taşır? → **Öneri:** mevcut
   `tenant_admin`/`analyst`'e **maplemeyin** — yeni bir `service_account` scope seti
   (`analyze:read/write`, `batch:submit`) tanımlayın; token; kullanıcı yönetimi,
   kimlik-bilgisi CRUD, token üretme, kurum silme uçlarına **erişememeli**.
6. **Token TTL & iptal SLA'sı:** Süresiz mi, zorunlu rotasyonlu mu (ör. 90 gün)?
   "Revoke sonrası bir sonraki istek reddedilir" garantisi verilecek mi?

### Kota, limit, header
7. **Rate limit semantiği:** "soft 60/dk" ile "hard 600/saat" nasıl bir arada?
   (60/dk = 3600/saat, hard tavanı 10 dk'da dolar → soft anlamsızlaşır.) soft =
   uyarı header + throttle mı, hard = 429 mı? `X-RateLimit-Reset` epoch mu delta mı?
8. **Kota birimi & penceresi:** Çağrı mı, LLM token'ı mı, ticket mi? Günlük mü
   faturalama-döngüsü mü? Aşımda **429 mı 402 mı**? (4 plan tier için rakamlar.)
9. **`X-Imga-Provider` çelişkisi:** Brief hem provider header'ı istiyor hem "AsakAI
   modeli bilmemeli" diyor — **doğrudan çelişki**. → **Öneri:** provider'ı tam opak
   tut; gerekirse yalnız stabil bir soyut etiket (`X-Imga-Engine: sentiment-v1`) dön.
10. **`cost_try`:** Parasal maliyet fiyat tarifesi + USD/TRY kuru + failover maliyet
    birleştirme gerektirir (ve tarife modelden türediği için model kimliğini sızdırır).
    → **Öneri:** v1'de `cost_try` yerine opak `units`/`quota_consumed` dön.

### Veri & KVKK
11. **Veri ikametgahı (B1):** Katı TR-residency taahhüdü verilecek mi? Verilecekse
    yurt dışı LLM'lerle **imkânsız** — ya TR-içi model yol haritası ya sözleşmede
    KVKK md.9 "yurt dışı aktarım + açık rıza" carve-out'u gerekir. Netleşmeden
    LLM-ağır use-case'ler için kickoff yapılmamalı.
12. **PII maskeleme:** LLM'e giden/AsakAI'ya dönen payload'da hangi alanlar
    (isim/e-posta/telefon/TCKN) maskelenmeli? Maskeleme mi tam redaksiyon mu?
    (Bugün yalnız **tespit** var — `customer_name` detector `is_pii` — **redaksiyon yok**.)
13. **Saklama & silme:** Denetim/analiz logu yasal saklama süresi (30 gün mü 12 ay mı)?
    `DELETE /v1/data/{session_id}` gerçek bir *session* kavramı gerektiriyor ama
    analyze **stateless** (`session_id` kodda **yok** — doğrulandı). Bu uç gerçek
    hard-delete garantisi veriyorsa entity + RLS + audit tasarlanmalı; no-op DELETE
    KVKK silme garantisi olarak sunulamaz.

### Analiz akışı
14. **`free-analyze` neyi streamliyor:** Çok-satırlı girdide satır-başı sonuç mu,
    tek metin için token-by-token anlatı mı? (İkincisi Gemini `stream=True` gerektirir;
    bugün **yok**.) Auth: tenant JWT/token mı, server-to-server paylaşımlı bearer mı?
15. **Route topolojisi:** 6 use-case ayrı endpoint mi, tek `/analyze` + `use_case`
    alanı mı? LLM anahtar sahipliği: kiracının kendi Gemini anahtarları mı, İmga
    sistem anahtarı mı? (İkisi farklı KVKK sorumluluk zinciri doğurur — bkz. §4A.)

---

## 2. İmga'da ZATEN Var Olan Güçlü Temel (yeniden-kullanım haritası)

Bu entegrasyonun çoğu "sıfırdan inşa" değil, kanıtlanmış kalıpların uygulanmasıdır.

| Brief gereksinimi | Mevcut İmga karşılığı | Durum |
|---|---|---|
| Çok-kiracılılık + izolasyon | RLS+FORCE tüm tenant-tablolarında; middleware `app.current_tenant_id`; `imga_app`/`imga_admin` rolleri | **Hazır** |
| Kiracı-başına sır saklama (create-once, last4, iptal) | `tenant_llm_credentials.py` + `TenantLlmCredential` (Fernet, RLS CRUD, role-gated) — **API token için birebir şablon** | **Hazır (klonlanır)** |
| Kimlik / oturum | JWT (15dk) + tek-kullanımlık refresh rotation + aile-ihlali tespiti; `require_role` RBAC | **Hazır** |
| Denetim izi | `LLMCallAuditor` (prompt hash, token, request_id, SAVEPOINT); `AuditService`; `DecisionAuditService` + okuma uçları | **Hazır** |
| Prompt yönetimi | `PromptResolver` (DB kayıt, tenant override, versiyon, required-var render) — SWOT/OKR/Briefing 3 canlı örnek | **Hazır** |
| LLM sağlayıcı sözleşmesi | `LLMProvider` ABC + temiz hata taksonomisi (`RateLimit`/`InvalidKey`/`LLMProviderError` → rotate) | **Hazır (soyutlama)** |
| Gemini failover | `GeminiKeyRotator` + `RotatingGeminiProvider` + `HybridClassifier` circuit breaker | **Hazır (anahtar-içi)** |
| SSE taşıması | `tenant_batch_progress.py` — keep-alive ping, disconnect, terminal event, teardown | **Hazır (iskelet)** |
| `free-analyze` | `public_trial` (tenant-bağımsız, persist etmez, 24s idempotency, KVKK GC) | **Neredeyse birebir** |
| `ticket-analyze` | `tenant_analyze` → `record_and_decide` → 5-dallı auto-ticket köprüsü | **Hazır (cephe)** |
| Request-ID korelasyon | `middleware/request_id.py` (inbound echo + ContextVar + log format) | **Hazır** |
| Test altyapısı | `infra/imga/test` canlı pg17+redis compose; 127 test dosyası; deterministik fixture piramidi | **Hazır** |

---

## 3. Boşluk + Efor Tablosu

| # | Alan | Durum | Efor | Ana yeni iş |
|---|---|---|---|---|
| 1 | Kimlik & API token (kiracı bearer, rotate, revoke) | Kısmi | **L** | `ApiTokenRecord` + migration (RLS), opak token mint/verify (HMAC+pepper), `get_current_user` çift-yol, scope'lu route'lar |
| 2 | Çok-kiracılılık & RLS & admin kurum yönetimi | **Var** | **S** | Yalnız: API token yolunun RLS'i doğru bağladığından emin ol (bkz. §4B) |
| 3 | LLM sağlayıcı soyutlama & çapraz-sağlayıcı router | Kısmi | **L** | `AsakAIProvider`, `load_active_keys(provider)` genelleştir, `ProviderRouter` failover katmanı, factory `asakai` dalı *(yalnız "AsakAI backend" yönü onaylanırsa)* |
| 4 | 6 use-case ↔ pipeline eşleşmesi | Kısmi | **L** | 2 cephe (free/ticket-analyze) ucuz; 4 net-yeni (anomaly-explain, return, cargo, suggest-reply) her biri prompt+şema+servis+test |
| 5 | Rate limit, kota, `X-*` header | Kısmi | **L** | `RateLimitHeaderMiddleware`, limiter'ı Redis'e taşı, per-tenant/token boyut, kota tablosu+enforce *(4–5 alt-sistem, bölünmeli)* |
| 6 | Loglama, KVKK, PII, purge, ikametgah | Kısmi | **L** | PII maskeleme pipeline'ı, DB audit retention worker, `IMGA_DATA_REGION`, `DELETE /v1/data`, hard-delete + consent |
| 7 | SSE / streaming (`free-analyze`) | Kısmi | **L** | Sonuç-seviyesi SSE route + event şeması, inline (Redis'siz) generator, (istenirse) Gemini token-stream |
| 8 | Health & sürümleme & gözlemlenebilirlik | Kısmi | **M** | `GET /health/ready` (DB+Redis+LLM), `/v1` prefix / `API-Version` header, request-id'yi arq/audit'e taşı |
| 9 | Test, contract parity, yük | Kısmi | **L** | `/v1` freeze, OpenAPI altın-snapshot testi, partner-auth fixture, k6/locust, SLO gate |

---

## 4. Risk Kaydı (kritik önce)

Toplam ~10 **kritik**, çok sayıda **yüksek** bulgu. Aşağıda temaya göre gruplanmış özet.

### 4A. KVKK / Veri İkametgahı — *en yüksek stratejik risk*
- **[KRİTİK] Gemini inference TR dışında çalışır, brief TR ikametgahını zorunlu kılıyor.**
  `gemini.py` sadece `genai.Client(api_key=...)` kuruyor; region/vertex/base_url yok →
  Google global (ağırlıkla ABD). Her analiz çağrısı ham müşteri metnini (PII olası)
  yurt dışına çıkarır. **Doğrudan ihlal.**
- **[KRİTİK] Vertex "europe-west" bile çözmez: Google'ın TR bölgesi yok.** Brief "AB
  kabul değil" diyerek AB-içi çözümü de reddediyor → Gemini/OpenAI/Anthropic hiçbir
  konfigürasyonla katı TR-residency'i sağlayamaz. **Tedarikçi-seviyesi imkânsızlık.**
- **[Yüksek]** LLM'e giden payload'da PII maskeleme yok (yalnız tespit var).
- **[Yüksek]** 30 gün retention + purge yok; `reviews.text` (ham PII) süresiz birikir,
  cleanup yalnız *dosya* siliyor.
- **[Yüksek]** `DELETE /v1/data/{session_id}` + gerçek hard-delete yok; tek silme
  geri-alınabilir soft-delete.
- **[Yüksek]** DPA alt-işleyen zinciri modellenmemiş; ayrıca trial'ın **İmga sistem
  anahtarını** kullanması İmga'yı bu aktarımda **doğrudan sorumlu** yapar.
- **[Orta]** Cloudflare proxy modu ikinci bir yurt-dışı-aktarım/alt-işleyen vektörü.

### 4B. Kimlik & Güvenlik Modeli
- **[KRİTİK] Makine token'ını `tenant_admin`/`analyst` rolüne maplemek = sızan
  token'la tam kurum ele geçirme.** RBAC kaba; o rol token'ı user yönetimi, kimlik-
  bilgisi CRUD, token üretme, kurum silme uçlarına da erişir. Least-privilege yok.
- **[KRİTİK] Token→tenant çözümü BYPASSRLS admin session'da kalırsa cross-tenant
  sızıntı.** Çözüm sonrası **hemen** `app_session`'a `set_current_tenant` ile geç;
  `is_super_admin=False` + `active_tenant_id IS NOT NULL` invariant'larını sert zorla.
- **[Yüksek]** 60s per-process `TTLCache` → revoke sonrası sızan token ~60s (worker
  başına) yaşar. Uzun-ömürlü token için otoriter/Redis kontrol şart.
- **[Yüksek]** Staging↔prod token karışması (ortak secret/pepper) → ortam-önekli
  token + per-env pepper ile yapısal reddet.
- **[Yüksek]** Per-token rate-limit yok → sızan token kurumun Gemini kotasını/LLM
  bütçesini sınırsız tüketir (**finansal DoS**).

### 4C. Mimari, Gecikme & Ölçek — *p95 < 3s SLA'sı yapısal risk altında*
- **[KRİTİK] Failover/retry bütçesi sınırsız.** `call_with_rotation` tüm anahtarları
  **seri** dener; istek-seviyesi deadline yok. En kötü N×15s (yapılandırılmış yolda
  N×~33s). p95<3s imkânsızlaşır. → Sıcak yola **hard per-request deadline** koy.
- **[KRİTİK] Senkron analyze'de İKİ seri Gemini round-trip (classify + embedding),
  üstelik AÇIK DB transaction içinde.** **Doğrulandı:** `tenant_analyze.py:205`
  transaction açıyor, `:243→:144` `await embed_text(...)` çağırıyor. → Embedding'i
  transaction ve senkron yoldan çıkar.
- **[Yüksek]** 10 req/s × ~3s tutma ≈ 30 eşzamanlı bağlantı > havuz (5+10=15) →
  havuz tükenir; noisy-neighbor. LLM I/O'yu transaction dışına al, havuzu boyutlandır.
- **[Yüksek]** BERT soğuk başlangıç: model lazy yükleniyor, warmup yok, image'a bake
  edilmiyor → ilk istek HF Hub'dan indirir. `/health/ready`'yi model-yüklü'ye bağla.
- **[Yüksek]** Senkron classify yolunda circuit breaker YOK → LLM outage'ında her
  istek tam timeout'u bekler; "İmga 500→AsakAI fallback" pratikte "İmga 15s asılır".
- **[Yüksek]** SSE "ilk token <800ms" sonuç-streaming ile karşılanamaz. → "ilk token"'ı
  anında preamble/ack event olarak tanımla.

### 4D. Kontrat Tutarlılığı
- **[KRİTİK]** `X-Imga-Provider` ↔ "model gizli" çelişkisi (bkz. §1.9).
- **[KRİTİK]** Kontrat dokümanı repoda yok (§1.2) — **doğrulandı**.
- **[Yüksek]** `DELETE /v1/data/{session_id}` stateless analyze'le çelişir (§1.13).
- **[Yüksek]** Domain TLD uyumsuzluğu `.tech`/`.ai` — **doğrulandı** (§1.3).
- **[Yüksek]** Request envelope (§2) içeriği hiçbir yerde tanımlı değil.
- **[Yüksek]** soft/hard rate limit semantiği çelişkili (§1.7).

### 4E. Kapsam & Zaman
- **[KRİTİK]** Brief gövdesi (normatif kontrat) tanımsız → 6 hafta bir *temenni*.
- **[KRİTİK]** Entegrasyon yönü çelişkili — iki mimari aynı anda kapsamda (§1.1).
- **[Yüksek]** 8×"L" kalem + `:5433` test vergisi 6 haftaya sığmaz.
- **[Yüksek]** Rate/kota/billing tek "L" değil, 4–5 alt-sistem.
- **[Yüksek]** Admin panel + 2. kiracı onboarding = tahminlenmemiş frontend işi.

---

## 5. Önerilen Yeniden Sıralama

> İlke: Önce **kontrat + kimlik + `/v1` freeze** (her şeyin bağlı olduğu kritik yol),
> sonra ucuz cepheler, en sona net-yeni LLM use-case'leri ve kota/billing.

**Sprint 13.0 — Kontrat Dondurma (≈1 hafta, kod yok):**
§1 sorularının kararı; kontrat dokümanı repoda; DTO + `use_case` enum + hata şeması;
`/v1` OpenAPI yüzeyi; **B1 veri-ikametgahı kararı** (bu netleşmeden LLM use-case'leri başlamaz).

**N+1:** `/v1` router prefix + OpenAPI altın-snapshot testi · **API token sistemi**
(scope'lu, opak, RLS testli) · 2 **cephe** endpoint (`free-analyze`, `ticket-analyze`)
· `/health/ready` + BERT warmup · sıcak-yola per-request deadline + circuit breaker.

**N+2:** 3–4 net-yeni LLM use-case (anomaly-explain, return, cargo, suggest-reply) —
her biri şeması kontrat-dondurmada kilitli · sonuç-seviyesi SSE · PII maskeleme (zorunluysa).

**N+3:** Redis-tabanlı per-tenant/token rate-limit + `X-RateLimit-*` header middleware ·
salt-okuma partner/audit dashboard'u · 2. kiracı onboarding (mevcut davet akışı MVP).

**v1'den ÇIKAR / SONRAYA:** AsakAI-as-backend çok-sağlayıcı router (yön onaylanana
kadar) · kota **enforcement** + billing sayaçları (greenfield, ayrı mini-sprint) ·
DSAR/hard-delete + audit-retention (ayrı compliance-sprint, yasal karara bağlı).

---

## 6. Birincil Kaynaktan Doğrulanan İddialar

Alt-ajan bulgularının en yüksek etkili olanları bizzat grep/read ile teyit edildi:

| İddia | Doğrulama | Sonuç |
|---|---|---|
| `imga.tech` domain'i repoda yok | `grep imga\.tech` | **0 sonuç** — domain uyumsuzluğu gerçek |
| `X-Imga-*` / `X-RateLimit` / `X-Quota` header'ları üretilmiyor | `grep` | **0 dosya** — hiç üretilmiyor |
| Kontrat dokümanı yok | `glob docs/**/imga-api-v1-contract*` | **Bulunamadı** |
| Senkron analiz DB transaction'ı içinde LLM/embedding çağırıyor | `tenant_analyze.py` read | **Doğru**: `:205 begin()` → `:243/:144 await embed_text()` |

> Mimarî SLA bulgularının (p95, havuz doygunluğu, soğuk başlangıç) sayısal
> büyüklükleri **analiz tahminidir**; kontrat-dondurma fazında **yük testiyle**
> (k6/locust, `generate_10k_csv` besleyici) ölçülmelidir.

---

## 7. Kapanış

İmga bu entegrasyonu taşıyabilir; eksik olan kod yeteneği değil, **kararlar ve bir
uyumluluk sorusu**. Aksiyon: (1) §1 sorularını AsakAI ile karara bağlayan
kontrat-dondurma toplantısı; (2) B1 veri-ikametgahı için VDD hukuk+strateji kararı;
(3) kontrat dokümanının repoya alınması. Bunlar netleştiğinde N+1 başarı kriteri
yazılabilir ve kodlama güvenle başlar.

**Yasal/DPA taahhüdü bu doküman kapsamında değildir** ve İmga backend ajanı
tarafından verilemez; §4A/§5'teki uyumluluk kalemleri VDD hukuk ekibinin kararına
bağlıdır.
