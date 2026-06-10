# Uzak inference + düzeltme-geri-besleme planı (2026-06-10)

Hedefler (ürün sahibi): (1) sunucuda model çalıştırmamak — GPU yok,
büyük yüklemelerde saatlerce bekleme + sistem yorgunluğu; (2) ücretsiz
kalmak (kart kabul, fatura yok); (3) eski sistemdeki "yanlış kararı
düzelt → model öğrensin" akışını yeni sisteme entegre etmek.
Hacim beklentisi: **50-250K satır/ay**. Veri gizliliği: üçüncü taraf
API kabul.

## 0. Keşif — mevcut durumun iki kritik gerçeği

**Gerçek 1 — darboğaz BERT değil.** Ölçüm: BERT CPU'da ~0.49 ms/satır
(2.852 satır ≈ 1.4 sn; `batch_analyzer.py` yorumları). Saatlerce süren
yüklemelerin kaynağı: düşük güvenli satırların kategori için **tek tek
Gemini'ye gitmesi** (~%30 satır × ~2 sn/çağrı, free-tier 10-15 RPM
limitiyle boğuluyor → 10K satırda 3K çağrı ≈ saatler). BERT'in gerçek
maliyeti RAM/CPU baskısı: paralel chunk başına ~500 MB model kopyası
(4 chunk = ~2 GB) + image'a gömülü 440 MB.

**Gerçek 2 — eski "Train & Save" modeli hiç eğitmiyordu.** Legacy
akış (legacy/app.py 506-518): düzeltme → `training_data.csv` append →
**birebir metin eşleşmeli** knowledge-base override (±0.9 skor, BERT'i
atlar). Fine-tuning kodu hiçbir sürümde yok; model stok
`savasy/bert-base-turkish-sentiment-cased`. Bu mekanizmanın çekirdeği
yeni pipeline'da zaten var (`imga-core/overrides/knowledge_base.py`)
ama CSV-bazlı, API'ye/web'e bağlı değil, tenant-scoped değil.

## 1. Güncel ücretsiz seçenekler (Haziran 2026 doğrulamalı)

| Seçenek | Ücretsiz koşullar | 50-250K satır/ay uyumu |
|---|---|---|
| **Gemini API free tier** | Flash: 10 RPM / 250K TPM / 1.500 istek/gün/key; Flash-Lite: 15 RPM (sınıflandırma için ideal); Pro artık faturalı. Kart yok. | 25 yorum/çağrı batch'leme ile 250K satır = 10K çağrı/ay ≈ 333/gün — **tek key ortalamada yeter**; 50K'lık tek günlük yükleme 2K çağrı = mevcut GeminiKeyRotator ile 2-3 key'de ~1 saat |
| **Modal** | $30/ay ücretsiz kredi, kart gerekmez, ms-bazlı faturalama, scale-to-zero | BERT CPU inference ayda toplam dakikalar mertebesinde çalışır → kredinin kuruşları; 440 MB model cold-start ~10-30 sn |
| **HF Spaces (free CPU)** | 2 vCPU / 16 GB ücretsiz; 48 saat hareketsizlikte uyur | BERT ~5-15 ms/satır → 50K satır 5-12 dk; cold-wake 1-2 dk; SLA yok |
| **HF Inference Providers** | Ücretsiz katman ~$0.10/ay kredi | **Yetersiz** — üretim için elenir |

Kaynaklar: [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) (free sayıları artık AI Studio'da; üçüncü taraf 2026 rehberleri: [tokenmix](https://tokenmix.ai/blog/gemini-api-free-tier-limits), [aifreeapi](https://www.aifreeapi.com/en/posts/gemini-api-rate-limits-per-tier)), [Modal pricing](https://modal.com/pricing), [HF pricing](https://huggingface.co/pricing).

## 2. Önerilen mimari — iki faz

### Faz A (asıl kazanç): Birleşik Gemini batch sınıflandırma

Sentiment + kategori, **tek structured-output çağrısında ~25 yorum**
birden. Mevcut akıştaki satır-başına kategori fallback'i tamamen
ortadan kalkar (asıl darboğaz buydu); BERT sıcak yoldan çıkar.

- Yeni `GeminiBatchClassifierAnalyzer`: `SentimentAnalyzer` arayüzünü
  (`analyze_batch(texts) -> list[AnalyzerPrediction]`) uygular —
  pipeline/worker DEĞİŞMEZ (`analyzers/base.py` soyutlaması temiz).
- Prompt: 25 yorum + tenant kategori listesi + (Faz C) tenant
  düzeltme örnekleri → JSON: `[{idx, sentiment, score, category,
  confidence}]`. Model: `flash-lite` (15 RPM, sınıflandırma odaklı).
- Mevcut GeminiKeyRotator + LLMCallAuditor aynen kullanılır.
- **Dayanıklılık:** AllKeysExhausted / circuit-breaker açıldığında
  otomatik **lokal BERT fallback** (image'da zaten var) + keyword
  kategori. Sistem Gemini'siz de ayakta kalır.
- Override katmanları (KB/critical/tier1/SLA/tier2) aynen üstte.

Beklenen etki: 10K satır ≈ 400 çağrı ≈ 2-3 key ile ~15-20 dk
(bugün: saatler). RAM baskısı: BERT yalnız fallback'te yüklenir
(lazy) → normal işleyişte ~2 GB serbest.

### Faz B (opsiyonel, A yetmezse): BERT'i Modal'a taşı

`RemoteHTTPSentimentAnalyzer` (HTTP POST /analyze-batch) + Modal'da
~40 satırlık FastAPI servis. Fallback bile sunucu dışına çıkar,
440 MB image'dan silinir. A fazı beklentiyi karşılarsa gereksiz.

## 3. Düzeltme-geri-besleme ("model öğrensin")

Eski mantığın modern, dürüst hali — üç katman:

1. **DB-bazlı düzeltme kaydı:** `review_corrections` tablosu
   (RLS+FORCE, tenant-scoped): review_id, eski/yeni sentiment +
   kategori, gerekçe, kullanıcı, zaman. Düzeltme `reviews` satırını
   da günceller (dashboard/analitik anında doğrulanır).
2. **Anında-etkili KB override (DB'den):** `reviews.text_hash`
   (normalize SHA-256) üzerinden birebir eşleşme — aynı metin bir
   daha gelirse düzeltilmiş karar uygulanır. CSV + restart yerine
   sorgu; tenant-scoped.
3. **Genelleme — few-shot besleme:** Gemini batch prompt'una
   tenant'ın güncel düzeltmelerinden K örnek (yorum → doğru etiket
   + gerekçe) eklenir. LLM düzeltme DESENİNİ benzer yorumlara
   uygular — "model öğreniyor" hissinin gerçek mekanizması.
   Gerçek fine-tuning istenirse: birikmiş düzeltmelerle Colab
   T4'te LoRA/klasik fine-tune + Modal/Space'e checkpoint —
   ayrı runbook, operasyonel yük (şimdilik önerilmiyor).

Web UI: review detayında "Kararı düzelt" (sentiment + kategori +
gerekçe); Sprint 9.8'deki test-feedback ekranıyla aynı dil.

## 4. RAG sorusu (ürün sahibinin sorusu üzerine analiz)

RAG = düzeltmeleri embedding'leyip yeni yorum için anlamsal komşu
düzeltmeleri getirip prompt'a koymak (+ çok benzer ise doğrudan
override). Değerlendirme:

- **Lehine:** Birebir eşleşmeyi aşar; "kargo 5 gündür gelmedi" ↔
  "kargom 1 haftadır yolda" eşleşir; düzeltme sayısı binlere
  çıktığında few-shot seçimini isabetli kılar.
- **Aleyhine (bugün):** Tenant başına düzeltme sayısı muhtemelen
  onlar-yüzler mertebesinde → few-shot'a SON N + kategori-eşleşen
  düzeltmelerin tamamı zaten sığar (10-20 örnek ≈ 2-4K token;
  250K TPM içinde önemsiz). pgvector, stok `postgres:17-alpine`
  imajında yok → imaj değişikliği + migration + embedding çağrısı
  (gemini-embedding free tier'ı dar) = bugün karşılığı olmayan
  karmaşıklık.
- **Karar önerisi:** Şimdi RAG'siz başla, tasarımı RAG-hazır yap:
  `review_corrections`'a nullable `embedding` kolonu + arayüzde
  "örnek seçici" stratejisi (bugün: recent+category; yarın:
  pgvector cosine). Tenant başına düzeltme ~200-500'ü aşarsa
  pgvector fazı açılır.

## 5. Uygulama sırası

1. `review_corrections` migration + correct endpoint + web UI
2. DB-bazlı KB override (text_hash lookup, pipeline'a katman)
3. `GeminiBatchClassifierAnalyzer` + few-shot besleme + BERT fallback
4. Batch worker entegrasyonu + ölçüm (10K test dosyasıyla süre kıyası)
5. (Koşullu) Modal offload / pgvector RAG fazı
