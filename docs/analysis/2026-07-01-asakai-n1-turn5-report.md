# İmga → AsakAI — Turn 5 Raporu (contract v1.2 hizalama + N+1 giriş)

**Tarih:** 2026-07-01 · **Faz:** N+0 kapanış → N+1 giriş · **Kaynak:** contract v1.2 (`d882162`)
**Bu rapor:** AsakAI'nin istediği 3 çıktı + contract v1.2 hizalama sonucu + kritik flag.

---

## 0. Contract v1.2 — okundu, hizalandı

`vdd-asakai/docs/imga-api-v1-contract.md` v1.2 (548 satır, 14 bölüm) baştan sona okundu.
Repoya v1.2 olarak mirror'landı (`docs/imga-api-v1-contract.md`). OpenAPI (`docs/openapi/v1.yaml`)
ve `apitokenrecord-migration-design.md` v1.2'ye göre revize edildi. 3 flag'imin de v1.2'de
kapatıldığını teyit ettim (§8.5 split, §7 SSE `processed_in`, §8.1 Stripe-style prefix + §8.6 opsBearer).

---

## 🔴 KRİTİK FLAG — mock client contract v1.2 ile UYUŞMUYOR

"Shape source of truth" dediğiniz `vdd-asakai/backend/app/imga/client.py`'yi okudum;
contract v1.2 ile **birden çok yerde çelişiyor.** İkisi de "source of truth" ama
birbirini tutmuyor — ve bu, tam da korktuğunuz "frontend patlar" senaryosu:

| Konu | Mock client (`client.py`) | Contract v1.2 | Etki |
|---|---|---|---|
| **Endpoint** | `POST {url}/v1/analyze` (tekil, satır 201) | `POST /v1/analyze/{use_case}` (§2) | Mock yanlış path'e gider → 404 |
| **Response shape** | flat: `{summary, action_items, usage:{prompt_tokens,completion_tokens}, model, confidence}` (satır 284-317) | `{ok, request_id, response:{…}, meta:{tokens:{prompt,completion,total}, cost_try, processed_in, cached}}` (§3) | Mock real-mode parser `data.usage.prompt_tokens` okuyor (satır 271) → contract'ta yok → sessizce `None`; frontend flat alan bekliyorsa **kırılır** |
| **Period enum** | `today, day, week, month, custom, all` (satır 43) | `day, week, month, custom` (§2) | `today`/`all` gönderilirse İmga 400 döner |
| **Ekstra header** | `X-Client-Request-ID` (satır 205) | contract'ta yok; `client_request_id` body'de | zararsız ama tanımsız |

**Karar (sizin):** contract-first kurala göre **contract kazanır** → mock client + onu
tüketen frontend, contract v1.2 envelope'una (§2/§3, per-use-case path) **güncellenmeli.**
Ben İmga'yı contract'a göre yazacağım; mock güncellenmezse benim (doğru) yanıtım
mock'un beklediğiyle uyuşmaz. Bu, contract test suite'inizin (§11.2 "envelope shape")
İmga'yı değil önce **kendi mock'unuzu** kırmasına yol açar. Önerim: contract test'i
mock'a değil, `docs/openapi/v1.yaml` (bu commit) + contract §3'e karşı yazın.

Ek küçük flag: contract §3 `AnalyzeError.code` TS enum'u **6 kod**; §5 tablosu **9**
(`residency_denied`, `session_not_found`, `export_window_too_large` eksik). §3 enum
güncellenmeli. OpenAPI'de union (9) aldım.

---

## Çıktı 1 — T3AI vs TİDE (DÜRÜST DURUM)

**Ben bir POC KOŞMADIM.** N+1 promptunuzda "N+0 son gününde POC yapıp aday belirlemiştin"
deniyor ama böyle bir şey konuşmalarımızda **olmadı** — ve ölçmediğim latency/kalite
sayılarını uydurmam. Bu, KVKK-kritik TR-inference kararı; uydurma benchmark en kötü
girdi olur. İşte gerçek durum + koşulabilir bir çerçeve:

**POC için gereken (henüz yok):** her iki sağlayıcının API erişimi/anahtarı, bir benchmark
harness'ı (örn. `test_10k_benchmark.py` deseninde), İmga'nın 6 use-case'inin temsili
prompt seti, ve TR-bölge latency ölçümü. Bunlar sağlanınca 1-2 günde ölçerim.

**Değerlendirme matrisi (POC bunları ölçmeli, ağırlıklı):**

| Kriter | Neden kritik | Ağırlık |
|---|---|---|
| **TR veri-ikametgahı garantisi** | §9 zorunlu; sağlayıcı inference'i fiziksel TR'de mi (ASN/traceroute kanıtı) | Elenme kriteri |
| **p95 latency < 3s** | §11.3 SLA; PII use-case'ler buna bağlı | Yüksek |
| **Structured/JSON output** | 6 use-case şema-kısıtlı çıktı ister (§4) | Yüksek |
| **Türkçe kalite** | ticket-analyze/suggest-reply müşteriye gider | Yüksek |
| **Batch + streaming** | free-analyze SSE ilk token <800ms (§11.3) | Orta |
| **Uptime/SLA + kota** | §11.1 7 gün kesintisiz | Orta |
| **API uyumu** | mevcut `LLMProvider` ABC'ye adapte kolaylığı | Orta |
| **Maliyet (TRY/token)** | `cost_try` faturalama (§3) | Orta |

**Ön eğilim (ölçümsüz, doğrulanmalı):** İmga'nın mevcut `LLMProvider` soyutlaması
her iki sağlayıcıyı da yeni bir provider sınıfıyla sarabilir; karar **ölçülen TR-latency
+ structured-output güvenilirliği**ne göre verilmeli. **Karar bende değil** — sağlayıcı
erişimi + ölçüm olmadan sorumlu bir "hangisi" diyemem. Erişim anahtarlarını verin,
POC'u gerçekten koşup 1 sayfa ölçülmüş özet döneyim.

---

## Çıktı 2 — OpenAPI v1.2 hizalanmış iskelet

`docs/openapi/v1.yaml` contract v1.2'ye göre yeniden yazıldı (16 route, 27 schema,
51 `$ref` — hepsi çözülüyor, YAML geçerli). v1.2 karşılıkları:

- **§2 envelope + §2.1 idempotency:** `AnalyzeRequestBase` (gerçek alanlar); `Idempotency-Replayed`
  response header + `meta.cached`.
- **§3.5 header matrisi:** 10 response header (`X-Imga-Request-Id`, `X-RateLimit-*`,
  `X-Quota-*`, `X-Imga-Tokens-Used`, `Idempotency-Replayed`, `X-Imga-Next-Cursor`) +
  request header'lar (`Accept-Residency`, `Accept-Language`, `X-Imga-PII-Mode`).
- **§4.1-4.6:** 6 use-case, gerçek context+response şemaları; free-analyze `user_prompt` zorunlu.
- **§4.7 `/health`:** status/version/region/providers (public). *(N+0'daki `/ready` kaldırıldı — contract'ta yok.)*
- **§4A admin (5 route):** tenants create, usage (opsBearer VEYA tenant), tokens rotate/revoke/list — tam şema.
- **§4.8/4.9 data:** DELETE `202` `EraseResponse`; GET export NDJSON `ExportRecord` + `X-Imga-Next-Cursor`.
- **§5:** `residency_denied` (403, ticket-* uçlarında), `session_not_found` (404), `export_window_too_large` (400).
- **§7 SSE:** `event: meta`'da `processed_in` normatif.
- **§8.6 opsBearer:** ayrı securityScheme; `imga_ops_*` prefix.
- **§11 kabul kriterleri:** `info.description`'a not.

İki flag dosyanın başına yorum olarak işlendi (mock mismatch + §3/§5 enum).

---

## Çıktı 3 — N+1 ilk hafta planı (auth dilimi)

**Hedef:** AsakAI staging'i mock'tan çıkarıp İmga staging'ine bağlayabilsin; auth temeli
+ endpoint iskeleti (mock yanıt) çalışsın. Test **`:5433` canlı-Postgres**'te yeşil
olmadan push yok → test koşumu `docs/handoffs/` ile sunucu ajanına.

| Gün | İş | Doğrulayan test (`:5433`) |
|---|---|---|
| **1** | Migration `0032`: `api_tokens` (RLS+FORCE, 0006 deseni) + `admin_tokens` (scope=ops) + indexler | migration up/down; RLS policy var; iki tablo |
| **2** | `ApiTokenRecord`/`AdminTokenRecord` modelleri + `ApiTokenService.mint/verify` (HMAC+pepper, `imga_live_`/`imga_stg_`/`imga_ops_*`) | mint→verify round-trip; hash lookup O(1); önek ortam eşleşmesi |
| **3** | `get_current_user` çift-yol (JWT ↔ API token) + `require_scope` + `ApiPrincipal`; admin BYPASSRLS→app_session rol devri | RLS izolasyon (A token B'yi görmez, `current_user=imga_app`); `require_role`→API token 403 |
| **4** | Cross-env enforcement (§8.1): `imga_stg_`→prod 401 `watch=wrong_environment`; opsBearer↔tenant 403 (§8.6); revoke ≤5s cache | wrong_environment 401; tenant→/admin 403; ops→analyze 403; revoke→sonraki 401 |
| **5** | Admin routes `/v1/admin/tokens` (rotate/revoke/list, opsBearer) + `/v1/analyze/{use_case}` **mock yanıt** iskeleti (contract §3 envelope) | rotate overlap; revoke propagation; 6 uç contract-shape mock döner |
| **6** | `tests/contract/` iskeleti: envelope shape (§2/§3) + error taxonomy (§5) + header matrisi (§3.5) mock yanıta karşı | contract test lokal yeşil |
| **7** | Ara: ruff + mypy strict + tüm testler; **sunucu ajanı handoff** ile `:5433` full koşum; N+1 ara raporu | test compose yeşil |

**Bağımlılıklar / bloklar:** (a) `IMGA_TOKEN_PEPPER` prod+staging secret store'da; (b) staging
deploy (`api-staging.imga.ai`) sunucu-ajanı işi; (c) TR-model POC erişimi (N+1 auth'u
bloklamaz ama N+2 için paralel başlamalı).

**N+1 tanımı gereği (DoD, §11 ile hizalı):** contract test suite lokal + `:5433` yeşil;
6 uç mock yanıtı contract-shape; auth rotate/revoke/cross-env testli; audit log (body YOK,
hash+metadata). Gerçek LLM + residency router N+2.

---

## Özet

Contract v1.2 hizalama tamam. En önemli çıktı **mock client ↔ contract uyuşmazlığı flag'i** —
bunu düzeltmeden İmga'yı doğru yazsam bile entegrasyon kırılır. POC için dürüstüm:
koşmadım, uydurmam; erişim verin ölçeyim. OpenAPI v1.2'ye hizalı ve doğrulandı. N+1 auth
dilimi 7 günlük plana bağlandı; "başla" + pepper + test-yolu onayıyla kod başlar.
