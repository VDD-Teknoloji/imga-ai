# Sprint 8.3.6 — SWOT + OKR + Multi-Key

**Status:** Active. Master reference for the entire sprint.

**Opens:** 2026-05-04. **Estimated:** ~1 week, 6 alt-faz.

**Test trajectory:** 150 → 200+. Migration: 0019 (forward-only). Endpoints: +7. Frontend pages: +3.

## Genel scope

`/strategy` (yeni sayfa) — SWOT + OKR raporları üreten, Gemini structured-output destekli, tenant-context-aware bir analiz katmanı. Her tenant kendi LLM API key'ini girer (multi-key rotation ile primary + fallback), encrypted (Fernet) DB'de saklanır. PDF export WeasyPrint. SWOT cache 24h Redis.

## Kullanıcı kararları (sabitler — değişmez)

1. **Taxonomy:** 23 → 21 kategori mevcut korunacak (Sprint 8.3.5'te pinlenmişti)
2. **OKR yaklaşımı:** B (zengin) — ayrı LLM call, Objective + 2-4 Key Results, structured output
3. **Tenant context:** industry (hibrit enum) + company_size (enum) + business_description (text)
4. **SWOT cache:** 24 saat (Redis, date_range bazlı key)
5. **Multi-key:** Primary + fallback drag-reorder
6. **PDF:** WeasyPrint
7. **Trigger:** Sprint 8.3.6 sadece manuel (otomatik raporlar Sprint 8.3.9'da)
8. **Retention:** süresiz
9. **Quota/cost tracking:** yok
10. **API key olmayan tenant:** SWOT/OKR butonu disabled + "Ayarla" CTA

## Mimari kararlar

### 1. Encryption flow

```
/etc/imga-secrets/master.key (host, root:root, chmod 700)
   ↓ Docker secret mount
/run/secrets/imga/master.key (ro)
   ↓ Fernet helper (imga_core.security.encryption)
DB: tenant_llm_credentials.encrypted_value (LargeBinary)
```

**Gemini API key hiçbir zaman .env'de tutulmaz.** Master key kayıp = encrypted data kayıp (manuel offline backup kullanıcı sorumluluğu, Sprint 9.0+ vault).

### 2. Redis cache

Yeni container (production+staging+test). Cache key pattern:

```
swot:{tenant_id}:{date_from}:{date_to}:{taxonomy_version}:{stats_hash}
```

TTL 86400. Maxmemory 256mb, allkeys-lru eviction.

### 3. SWOT response_schema (structured output, regex parsing yok)

```python
SWOT_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["strengths", "weaknesses", "opportunities", "threats", "strategic_recommendations"],
    "properties": {
        "strengths": {
            "type": "array", "minItems": 2, "maxItems": 6,
            "items": {
                "type": "object",
                "required": ["title", "description", "evidence"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence": {"type": "string"}  # Hangi metrik/sayı destekliyor
                }
            }
        },
        # weaknesses, opportunities, threats — aynı yapı
        "strategic_recommendations": {
            "type": "array", "minItems": 3, "maxItems": 5,
            "items": {
                "type": "object",
                "required": ["title", "description", "priority", "estimated_impact"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"enum": ["yüksek", "orta", "düşük"]},
                    "estimated_impact": {"enum": ["yüksek", "orta", "düşük"]}
                }
            }
        }
    }
}
```

### 4. OKR response_schema

```python
OKR_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["objectives"],
    "properties": {
        "objectives": {
            "type": "array", "minItems": 2, "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["objective", "rationale", "key_results"],
                "properties": {
                    "objective": {"type": "string"},
                    "rationale": {"type": "string"},
                    "key_results": {
                        "type": "array", "minItems": 2, "maxItems": 4,
                        "items": {
                            "type": "object",
                            "required": ["text", "metric", "baseline", "target"],
                            "properties": {
                                "text": {"type": "string"},
                                "metric": {"type": "string"},
                                "baseline": {"type": "string"},
                                "target": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
    }
}
```

### 5. Multi-key rotation

- `GeminiKeyRotator` class
- Priority-ordered list (primary, fallback_1, fallback_2, ...)
- `RateLimitError` → next key
- `InvalidKeyError` → mark failed (`last_failed_at`), next key
- All exhausted → `AllKeysExhaustedError` (kullanıcıya şeffaf hata, "tüm anahtarlar tükendi")

### 6. Tenant context injection

- **INDUSTRY_OPTIONS:** `e_commerce`, `retail`, `telecom`, `banking`, `insurance`, `services`, `healthcare`, `education`, `manufacturing`, `food_beverage`, `logistics`, `other`
  - `other` → `industry_other_text` zorunlu (max 128 karakter)
- **COMPANY_SIZE:** `solo` (1), `small` (2-10), `medium` (11-50), `large` (51-250), `enterprise` (251+)
- **business_description:** max 500 karakter

Her SWOT/OKR çağrısında prompt'a inject edilir; LLM tenant'ın sektörüne ve büyüklüğüne göre özelleştirilmiş analiz üretir.

### 7. Bug 2 patch (tense varyantları) Sprint 8.3.6.1 prework'ünde

Sprint 8.3.5.6'da raporlanan "Heuristic tense varyantları kaçırıyor" bug'ının kritik 5-6 keyword'ünü Migration 0019'da existing taxonomies'e UPDATE ile ekle. Tam çözüm Sprint 8.3.7'ye (taxonomy edit UI) birleştirildi.

```python
TENSE_VARIANT_PATCHES = {
    "shipment_not_arrived": ["gelmiyor", "ulaşamıyorum", "ulaşamadı", "ulaşmıyor"],
    "broken_damaged": ["kırılmış", "deforme olmuş"],
    "refund_not_received": ["param yatmıyor", "iade gelmedi henüz"],
    "cancel_request": ["iptal istiyorum", "iptal edebilir miyim"],
    "address_change": ["adresimi değiştirebilir miyim", "yanlış adres yazdım"],
    "how_to_return": ["nasıl iade edeceğim", "iade prosedürü"],
}
```

Yeni tenant'ların default seed'i de güncellenir (`taxonomy_service.py`) — migration sadece var olan tenant rows için.

## Alt-faz tablosu

| Alt-faz | Konu | Migration | Test | Süre |
| --- | --- | --- | --- | --- |
| 8.3.6.1 | Prework (master key, Redis, encryption helper, migration 0019, tense patch) | 0019 | +5 fixture/encryption | 1 gün |
| 8.3.6.2 | LLM Provider + Multi-Key Rotation | — | +12 | 1 gün |
| 8.3.6.3 | SWOT Generator Service | — | +10 | 1 gün |
| 8.3.6.4 | OKR Generator Service | — | +8 | 0.5 gün |
| 8.3.6.5 | Endpoints + WeasyPrint | — | +14 | 1.5 gün |
| 8.3.6.6 | Frontend (3 sayfa) | — | +10 | 1.5 gün |

**Toplam yeni test:** 59. **Test trajectory:** 150 → ~209.

## Frontend navigation

Mevcut menüye **"Strateji"** eklenecek (Görselleştirme'den sonra, Biletler'den önce).

3 yeni sayfa:

- `/strategy` — SWOT + OKR generator + history list
- `/settings/integrations` — multi-key drag-reorder UI (primary + fallback)
- `/settings/profile` — tenant context (industry/size/description)

## Mühendislik standartları (Sprint 8.3.5'ten devralınan)

- **URL State Path B + Suspense** — [docs/agent-rules/url-state-patterns.md](../agent-rules/url-state-patterns.md). `/strategy` filter + history list + `/settings/integrations` reorder UI bu pattern'i kullanır
- **JSONB @> containment** pattern (Sprint 8.3.4 round-1 öğrenmesi)
- **Forward-only migration** standardı
- **Push öncesi pytest mecburi** (test compose green)
- **Round 1 → Round 2 disiplini** — production smoke geçmeden alt-faz kapanmaz
- **Async state mirror eslint-disable + intent comment** (Sprint 8.3.5.6 round-1 baseline)
- **Production browser smoke** (dev compose ayağa kalkmazsa)

## Risk konuları (kabul edilmiş)

- **Master key kayıp** = encrypted data kayıp (manuel offline backup kullanıcı sorumluluğu, Sprint 9.0+ vault)
- **Gemini quota** → multi-key rotation absorbe eder, kullanıcıya şeffaf hata
- **Hallucinated stats** → `evidence` field zorunluluğu mitigation
- **WeasyPrint Docker image** +80-100 MB → kabul edilebilir

## Sunucu ajan paralel iş

- `/etc/imga-secrets/` dizinini oluştur (root sudo)
- Production master key generate et
- Compose'da secrets mount + Redis service ekleme PR'ı (sunucu repo'sunda)

Local ajan test compose için master key + Redis kurar; sunucu ajan production için. Senkronizasyon kullanıcı koordineli.
