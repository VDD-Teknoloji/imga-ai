# AsakAI v1 — N+0 Kontrat-Dondurma Yanıtı (İmga → AsakAI)

**Tarih:** 2026-07-01 · **Faz:** N+0 (kontrat-dondurma) · **Karşı taraf brief:** v1.1 (AsakAI `92cdb1e`)
**Önceki inceleme:** [2026-07-01-asakai-imga-v1-kickoff-review.md](2026-07-01-asakai-imga-v1-kickoff-review.md)
**Bu doküman:** rapor §1'in 15 kararına v1.1'e göre revize yanıt + timeline değerlendirmesi + B2 tercihi.

> **Durum:** Kod yazılmadı. Bu bir kontrat-freeze girdi dokümanıdır. Aşağıdaki
> `✅ MUTABIK` / `⚠️ KONTRAT GEREK` (contract §-metni gerekiyor) / `🚩 İTİRAZ`
> (görüşülmesi gereken sert itiraz) / `🔎 AÇIK` (henüz çözülmedi) etiketleri AsakAI
> ile son turda netleşecek noktaları işaretler.

---

## 0. Kapatılan blokajlar (teyit)

| Blokaj | v1.1 kararı | İmga tarafı |
|---|---|---|
| B1 residency | **Hybrid** (PII'siz→outbound OK, PII'li→TR-içi, free-analyze varsayılan TR + `Accept-Residency` opt-out) | ✅ Prensipte mutabık — **ancak yeni iş kolu doğuruyor**, bkz. §2 ve §3 |
| B2 kontrat | Doküman v1.1 mevcut (`92cdb1e`) | ⚠️ Henüz İmga reposunda/elimizde **değil** — bkz. §4 (tercih) |
| B3 yön | Tek yön **AsakAI ⇒ İmga** (client-server); §3.5 router yalnız İmga-içi | ✅ Mutabık — **nüans:** İmga-içi router artık *residency* için v1'de zorunlu, bkz. §2.1 |

---

## 1. 15 Kararın Revize Yanıtı

### Sözleşme & yön
1. **Entegrasyon yönü** — ✅ **MUTABIK.** AsakAI ⇒ İmga tek yön. AsakAI-as-backend
   provider işi v1'den çıktı. *Nüans:* İmga-içi sağlayıcı soyutlaması yine gerekli
   ama artık **AsakAI için değil, residency yönlendirmesi için** (bkz. §2.1).
2. **Kontrat dokümanı** — ⚠️ v1.1 var ama elimizde yok; §4'teki tercihe göre repoya
   alınınca OpenAPI iskeleti (`docs/openapi/v1.yaml`) **§2 request envelope**'una
   göre kesinleşecek. Şu anki iskelet brief özetinden türetildi, `TODO(contract §2)`
   ile işaretli.
3. **Domain** — ✅ **MUTABIK.** Kanonik `imga.ai`. (`.tech` referansları düşürüldü.)

### Kimlik & yetki
4. **API token modeli** — İmga kararı: **opak + DB'de hash'li** (HMAC-SHA256 + per-env
   pepper), `imga_sk_live_` / `imga_sk_test_` önekli. Stateless api-JWT reddedildi
   (iptal edilemez). Tasarım: [apitokenrecord-migration-design](2026-07-01-apitokenrecord-migration-design.md).
   ⚠️ Brief §8 auth-flow'unun bu modelle çeliştiği bir nokta varsa flag'leyin.
5. **Token scope/rol** — İmga kararı: **yeni `service_account` scope seti**
   (`analyze:read`, `analyze:write`, `batch:submit`, `health:read`). Mevcut
   `tenant_admin`/`analyst`'e **maplenmeyecek** (sızan token'la kurum ele geçirme
   riski). ⚠️ AsakAI'nin gerçekten çağıracağı **minimum uç kümesini** verin ki
   scope beyaz-listesi tam olsun.
6. **Token TTL & iptal SLA'sı** — İmga kararı: varsayılan **90 gün + zorunlu rotate**;
   "revoke → bir sonraki istek reddedilir" garantisi (otoriter/Redis kontrol, per-process
   cache'e bağlanmayacak). ✅ Bunu N+1 başarı kriteri yapıyoruz.

### Kota, limit, header
7. **Rate limit semantiği** — ⚠️ **KONTRAT GEREK.** "soft 60/dk" + "hard 600/saat"
   matematiksel olarak çelişik (60/dk = 3600/saat, hard 10 dk'da dolar). İmga önerisi:
   **soft = burst** (aşımda `X-RateLimit` uyarı header + throttle, 200), **hard =
   sustained** (aşımda 429 + `Retry-After`). v1.2'de netleşsin.
8. **Kota birimi & penceresi** — ⚠️ Rakamlar contract'ta netleşmeli. İmga önerisi:
   LLM-token bazlı, aylık pencere. **Billing/router sayaçları v1'den ÇIKTI**
   (AsakAI "kabul" verdi). Kota *enforcement*'ın (reddetme) ertelenmesi ise **İmga
   önerisi — v1.2'de teyit**; v1'de yalnız *sayaç/gözlem* (`llm_call_audit` üzerinden).
9. **`X-Imga-Provider`** — ✅ **ÇÖZÜLDÜ** (alt-nokta ⚠️ contract §3 teyit — bkz. §5.8).
   v1.1: staging-only; prod'da opak kod (`prov_a`, `prov_tr_1`), `meta.model` opak.
   *Kalan alt-nokta:* `prov_tr_1` gibi kodlar **residency sınıfını** (TR/outbound)
   sızdırabilir — tam opaklık isteniyorsa kodlar bölge belirtmesin (`prov_1`, `prov_2`).
10. **`cost_try`** — 🔎 **AÇIK.** v1.1 `meta.model`'i opak yaptı ama `cost_try`'a
    değinmedi. İmga önerisi: v1'de parasal alan yerine opak `units`/`quota_consumed`.
    `cost_try` kalacaksa kur kaynağı + snapshot politikası contract'a bağlansın.

### Veri & KVKK
11. **Residency** — ✅ Hybrid mutabık; **🚩 en büyük ikinci-derece sonuç:** PII'li
    use-case'ler (`ticket-analyze`, `ticket-suggest-reply`) + varsayılan `free-analyze`
    **TR-içi model gerektiriyor** → İmga'nın bir **TR çıkarım hizmeti ayağa kaldırması**
    gerek. Bu, orijinal tahminde **yok**. Detay §2 + §3 (timeline).
12. **PII maskeleme** — ⚠️ Hybrid'de PII TR-içinde kaldığı için residency-amaçlı
    maskeleme gevşer; ama (a) log/retention ve (b) `Accept-Residency: outbound-ok`
    ile dışarı çıkan `free-analyze` için maskeleme **hâlâ gerekli**. Hangi alanlar
    (isim/e-posta/telefon/TCKN) ve maskeleme mi tam redaksiyon mu → contract §5/§9.
13. **Retention & `DELETE /v1/data/{session_id}`** — ⚠️ **KONTRAT GEREK.** analyze
    stateless; `session_id` kodda yok. Bu uç gerçek hard-delete garantisi veriyorsa
    session entity + RLS + audit tasarlanmalı; contract §9'da `session_id` üretimi ve
    kapsamı tanımlı mı? No-op DELETE KVKK garantisi olarak sunulamaz.

### Analiz akışı
14. **`free-analyze`** — ✅ `Accept-Residency: outbound-ok` opt-out modeli mutabık.
    ⚠️ **Açık:** stream'lenen ne — çok-satırlı girdide satır-başı sonuç mu, tek metin
    için token-by-token anlatı mı? İkincisi Gemini `stream=True` gerektirir (bugün yok);
    TR-model için de streaming yeteneği ayrı doğrulanmalı. Contract §7'de netleşsin.
15. **Route topolojisi & anahtar sahipliği** — ⚠️ Contract'tan 6 ayrı endpoint (OpenAPI
    iskeleti buna göre). Anahtar sahipliği: **outbound** use-case'ler tenant Gemini
    anahtarı (mevcut rotator) mı İmga sistem anahtarı mı; **TR-model** büyük olasılıkla
    İmga-hosted sistem kaynağı. Contract §5'te teyit — KVKK sorumluluk zincirini bu belirler.

---

## 2. Hybrid Residency'nin Net-Yeni İş Kolu (kritik flag)

### 2.1 İmga-içi "residency-aware router" v1'de ZORUNLU oldu
B3 "AsakAI'ya router davranışı yok" doğru; ama Hybrid, İmga-içinde her isteği
**PII-sınıfı + `Accept-Residency` header'ına göre** doğru arka uca yönlendiren bir
router gerektiriyor:

| Use-case | Varsayılan hedef | Header ile |
|---|---|---|
| anomaly-explain, cargo-optimize, return-analyze | Outbound LLM (Gemini) | — |
| ticket-analyze, ticket-suggest-reply | **TR-içi model** (zorunlu) | — |
| free-analyze | **TR-içi model** | `Accept-Residency: outbound-ok` → outbound (AsakAI m.9 rıza akışını tetikler) |

İyi haber: İmga'nın mevcut `LLMProvider` ABC + `create_llm_provider` factory bu router'ın
temeli; kötü haber: bir **TR-model provider'ı** (`LLMProvider` implementasyonu) ve router
politikası net-yeni.

### 2.2 TR-içi model = ayrı, tahminlenmemiş bir iş kolu
Aday liste (Sailor / T3AI / TİDE / self-host Llama-3-8B-TR) iki köklü senaryo doğurur:
- **Managed TR API (T3AI/TİDE gibi):** "sadece" yeni bir `LLMProvider` + kimlik-bilgisi
  satırı (mevcut `tenant_llm_credentials` şablonu) — **orta** efor. Ama p95<3s ve
  batch/structured-output yeteneği doğrulanmalı.
- **Self-host Llama-3-8B-TR:** GPU tedariki + serving (vLLM/TGI) + TR-bölge hosting +
  latency/ölçek doğrulama — **büyük** efor, ayrı altyapı iş kolu.

**🚩 Bu karar timeline'ı doğrudan belirler (bkz. §3).** N+0 çıktısı olarak: TR-model
**managed mı self-host mu**? En kritik açık soru.

---

## 3. Timeline Değerlendirmesi (deliverable 4)

**v1.1 §6, N+2'yi 3 hafta / "residency-aware router + PII scrubbing" olarak konumluyor.**

**🚩 İtiraz:** Bu tablo, *router'ın yönlendireceği TR-modelin var olduğunu* varsayıyor
ama o modeli **ayağa kaldırma işini kapsamıyor**. "Residency-aware router + PII scrubbing"
mevcut olmayan bir hedefe yönlendirme yapamaz. Yüzeyin yarısı (2 PII use-case + varsayılan
free-analyze) TR-modele bağımlı → **TR-model kritik yolda**.

**İmga revizyon önerisi:**

| Faz | v1.1 §6 (bizim anladığımız) | İmga önerisi |
|---|---|---|
| **N+0** | kontrat-dondurma | + **TR-model kararı** (managed vs self-host) + latency/batch spike |
| **N+1** | token + facade + /v1 | Aynı + `tenant_analyze` DB-txn×LLM refaktörü + **sıcak-yol per-request hard deadline + senkron classify circuit breaker + BERT warmup/`health/ready`** (kickoff §4C/§5 SLA kalemleri — sessizce düşürülmemeli) + **TR-model provider entegrasyonu** (managed ise) |
| **N+2** | residency-aware router + PII scrubbing (3 hafta) | Router + PII scrubbing + 2 PII use-case — **yalnız TR-model N+1'de hazırsa 3 hafta yeter**; self-host seçilirse N+2 3 hafta **yetmez**, ayrı altyapı sprinti gerekir |
| **N+3** | 2. kiracı + admin panel | + kalan net-yeni LLM use-case (anomaly/return/cargo) + rate-limit header middleware |

**Özet:** v1.1 §6'yı **koşullu kabul** ediyoruz — **koşul: TR-model managed API olarak
seçilir ve N+1'de entegre edilir.** Self-host Llama seçilirse §6 gerçekçi değil; TR-model
altyapısı için ayrı bir iş kolu/sprint eklenmeli. Bu kararı N+0'da verelim.

> **N+1 gerçekçilik notu:** v1.1 §6'da N+1 yalnız "token + facade + /v1" idi; yukarıdaki
> öneride N+1'e **TR-model entegrasyonu + `tenant_analyze` refaktörü + SLA sertleştirmesi**
> eklendi. N+2'ye uyguladığımız "sığar mı" testini N+1'e de uygulamalıyız — bu haliyle N+1
> de gerginleşti; TR-model *self-host* ise N+1 tek başına yetmez. Kesin süreyi TR-model
> kararı (§2.2) belirleyecek.

---

## 4. B2 — Kontrat Dokümanı Teslim Tercihi (yanıt)

**Tercih: kontrat dokümanını İmga reposuna commit'leyin** (`docs/imga-api-v1-contract.md`,
v1.1), ya da tam metnini bu kanala yapıştırın. Gerekçe:
- Her iki taraf **aynı versiyonlu dosyaya** diff atar; İmga CI'ı OpenAPI iskeletini
  bu dosyaya karşı doğrulayabilir (`docs/openapi/v1.yaml` ↔ contract §2 parity testi).
- Private-repo read-only erişim veya Gist de olur **ama** version-control kopukluğu
  doğurur ve harici kaynaktan otomatik çekme benim tarafımda ek yetki/kurulum gerektirir.
- **En pratik:** contract dosyasını İmga reposuna (veya paylaşılan bir yere) ekleyin;
  ben OpenAPI'yi ona göre kesinleştireyim. Şu anki `v1.yaml` iskeleti **§2 gelene kadar
  provisional** ve `TODO(contract §2)` işaretli.

---

## 5. Kalan açık sorular (v1.2'de kapanmalı)

1. **TR-model: managed mı self-host mu?** (timeline'ın tek en kritik girdisi — §2.2)
2. Contract §2 **request envelope** tam alan listesi (OpenAPI'yi kilitlemek için).
3. Rate limit soft/hard semantiği (§1.7) + kota birimi/penceresi rakamları (§1.8).
4. `cost_try` kalıyor mu, opak `units` mı (§1.10)?
5. `session_id` / `DELETE /v1/data` gerçek entity mi (§1.13)?
6. `free-analyze` token-stream mi satır-stream mi (§1.14)?
7. AsakAI'nin çağıracağı **minimum endpoint + scope** kümesi (token beyaz-listesi, §1.5).
8. Sağlayıcı opak kodları residency sızdırmasın mı (`prov_tr_1` → `prov_1`, §1.9)?
