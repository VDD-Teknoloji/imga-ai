# Handoff: batch-audit-and-sse-polling-hotfix

**Tarih:** 2026-05-13
**Sprint:** 9.5.5 hotfix önerisi
**Yazar:** server-agent
**Hedef:** local-agent
**Durum:** open
**Öncelik:** orta — demo blocker değil ama kullanıcı gözlemlenebilirliği zayıflattı

## Bağlam

Sprint 9.5.4 production smoke (12-13.05.2026) iki ayrı kullanıcı şikâyeti üretti:

1. **`/admin/llm-audit` batch satırlarında "0 tok · 0ms"** → kullanıcı "Gemini gerçekten kullanılıyor mu?" sorgulaması yaptı; faturasız zannedildi.
2. **Toplu yükleme bittikten sonra UI hâlâ "yükleniyor"** → SSE bağlantısı `complete` event'ini kaçırınca React state stale kalıyor, hard refresh sonrası bile takılı.

Backend dataya zarar yok (4 batch × 98 = 392 review insert edildi, Gemini gerçekten çağrıldı). İki bug da görüntü/observability seviyesinde.

## Bug A — `llm_call_audit` batch satırlarında token + duration eksik

### Kanıt

```
classification | gemini-2.5-flash | input_tokens=NULL | output_tokens=NULL | total_tokens=0 | duration_ms=0    ← BATCH (boş)
briefing       | gemini-3-flash-preview | input=578 | output=409 | total=987 | duration=9083    ← BRIEFING (dolu)
```

### Kök neden

`packages/imga-api/src/imga_api/workers/batch_analyzer.py` chunk_auditor pattern'i:

```python
async with chunk_auditor:
    # The BERT/LLM call already ran outside the transaction (line ~739)
    chunk_auditor.mark_fallback_used(llm_fallback_count > 0)
    chunk_auditor.record_success()    # ← parametre YOK
```

İki sorun:

**A1 — token args eksik:** `record_success()` `input_tokens` / `output_tokens` defaultları None. DB'de NULL → `total_tokens` GENERATED ALWAYS expr'inden 0 çıkıyor.

Karşılaştırma `executive_briefing_service.py` doğru pattern:
```python
auditor.record_success(input_tokens=token_usage.get("input"), output_tokens=token_usage.get("output"))
```

**A2 — duration_ms ~0ms:** `LLMCallAuditor.__aenter__` `_started_at = time.monotonic()` set ediyor. Ama batch path'inde `async with` bloğu gerçek LLM çağrısının ÇIKTISINDAN SONRA açılıyor — sadece flag çağrıları wrap ediyor (<1ms). Gerçek LLM süresi (HybridClassifier `duration=79.06s`) auditor'a hiç geçmiyor.

### Plumbing zinciri ve önerilen fix

`HybridClassifier.classify_batch_async` şu an `list[CategoryClassification]` dönüyor; aggregate token+duration döndürmüyor.

**Adım 1** — `LLMProvider.classify` interface'ine token info ekle (option A — backward-compat metadata dict):
```python
# CategoryClassification.metadata['token_usage'] = {'input': N, 'output': M}
```

**Adım 2** — `GeminiProvider.classify` SDK response'undan `usage_metadata` çekip metadata'ya yazsın.

**Adım 3** — `HybridClassifier.classify_batch_async` per-LLM-result token'ı aggregate edip yeni dataclass döndürsün:
```python
@dataclass
class BatchClassificationResult:
    classifications: list[CategoryClassification]
    llm_total_input_tokens: int
    llm_total_output_tokens: int
    llm_duration_ms: int
```

**Adım 4** — `batch_analyzer.py`:
```python
result = await classifier.classify_batch_async(...)
analyses = result.classifications
...
chunk_auditor.record_success(
    input_tokens=result.llm_total_input_tokens,
    output_tokens=result.llm_total_output_tokens,
    duration_ms=result.llm_duration_ms,  # yeni param
)
```

**Adım 5** — `LLMCallAuditor.record_success` signature'ına `duration_ms: int | None = None` ekle. `_insert_row` `elapsed = self._duration_ms_override or default_elapsed`.

### Dokunulan dosyalar

- `packages/imga-core/src/imga_core/llm/base.py` (LLMProvider interface)
- `packages/imga-core/src/imga_core/llm/gemini.py` (GeminiProvider.classify)
- `packages/imga-core/src/imga_core/classifiers/hybrid.py` (classify_batch_async return tipi)
- `packages/imga-api/src/imga_api/workers/batch_analyzer.py` (chunk_auditor.record_success çağrısı)
- `packages/imga-api/src/imga_api/services/llm_audit_service.py` (record_success duration param)
- `packages/imga-api/tests/test_batch_audit_token_capture.py` (yeni test)

### Kabul kriterleri

```sql
SELECT call_type, total_tokens, duration_ms FROM llm_call_audit
WHERE related_entity_type='analyze_batch_job' ORDER BY created_at DESC LIMIT 1;
-- total_tokens > 0, duration_ms ≈ HybridClassifier.duration (~50-100K token, ~80000ms 98-row batch için)
```

## Bug B — SSE bağlantısı `complete` kaçırınca UI stale

### Kanıt

- Backend: batch 02:31:00 UTC'de COMPLETED, processed_rows=98
- Frontend: 5+ dk sonra hâlâ "yükleniyor"
- Hard refresh sonrası bile takılı (yeni SSE bağlantısı yine `complete` event'ini kaçırdı)
- Pattern her batch'te tekrar ediyor

### Kök neden

`packages/imga-web/src/components/batch/BatchProgressStream.tsx` SSE-only:

```tsx
const handle = openSseStream(url, {
  reconnect: true,
  handlers: {
    progress: ...,
    complete: ...,
  },
});
```

`reconnect: true` blip'leri toleranslıyor ama:
1. Reconnect window içinde backend `complete` emit ederse → kaçırma
2. `_TERMINAL_LINGER_SECONDS = 5.0` backend stream'i terminal state sonrası 5s kapatıyor
3. `onError` handler var ama polling fallback yok

Cloudflare 100s idle kill + tek `complete` event'i kaçırılırsa kullanıcı kalıcı stale.

### Önerilen fix — polling fallback

`BatchProgressStream.tsx` useEffect içinde:

```tsx
const POLLING_INTERVAL_MS = 5000;
const SSE_QUIET_TIMEOUT_MS = 30000;

let lastEventAt = Date.now();
let pollingTimer: ReturnType<typeof setInterval> | null = null;

const startPolling = () => {
  if (pollingTimer) return;
  pollingTimer = setInterval(async () => {
    try {
      const job = await apiRequest<BatchJob>(`/tenants/me/analyze/batch/${jobId}`);
      const snap = batchJobToSnapshot(job);
      setSnapshot(snap);
      if (TERMINAL_STATUSES.has(snap.status)) {
        if (!completedRef.current) {
          completedRef.current = true;
          onComplete?.(snap);
        }
        clearInterval(pollingTimer!); pollingTimer = null;
        handleRef.current?.close();
      }
    } catch {}
  }, POLLING_INTERVAL_MS);
};

const handle = openSseStream(url, {
  reconnect: true,
  handlers: {
    progress: (p) => { lastEventAt = Date.now(); setSnapshot(p as BatchProgressSnapshot); },
    complete: ...,
  },
  onError: () => { startPolling(); },
});

const watchdog = setInterval(() => {
  if (Date.now() - lastEventAt > SSE_QUIET_TIMEOUT_MS) startPolling();
}, 5000);

return () => {
  clearInterval(watchdog);
  if (pollingTimer) clearInterval(pollingTimer);
  handleRef.current?.close();
};
```

`batchJobToSnapshot()` küçük helper — `BatchJob` (DB row) → `BatchProgressSnapshot` shape eşle.

### Kabul kriterleri

- Network DevTools'tan SSE "stalled" yap (browser offline 30s) → component DB poll'a düşmeli, batch tamamlanınca "Tamamlandı" göstermeli
- `completedRef` debounce ile duplicate `onComplete?` çağırılmamalı

## Talep

İki commit:

**Commit 1:**
```
fix(api,core): batch chunk audit captures real token usage + LLM duration (Sprint 9.5.5 A)
```

**Commit 2:**
```
fix(web): BatchProgressStream falls back to DB poll when SSE goes quiet (Sprint 9.5.5 B)
```

`sprint-9.5` tag DOKUNULMAZ (a2e8563'te kalır, hotfix tag dışı).

## Cevap

(local-agent: commit hash + push doğrulamasını buraya yaz)
