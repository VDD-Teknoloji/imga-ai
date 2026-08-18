# Düzeltme-RAG mimarisi — mevcut durum, ölçülen sınırlar, karar (2026-08-18)

WS3 kapsamında düzeltme-geri-besleme (correction feedback) katmanının
mimari değerlendirmesi. Hedef: yeniden inşa değil, ölçümle doğrulanmış
darboğazlara hedefli müdahale. Kısa, mühendis-okur.

## 1. Mevcut üç katman

Kaynak: `packages/imga-api/src/imga_api/services/correction_store.py`,
`services/embedding_service.py`, `workers/batch_analyzer.py::_few_shot_for_chunk`,
`routes/tenant_analyze.py::_apply_manual_corrections`.

Bir yorum düzeltildiğinde (`POST /tenants/me/reviews/{id}/correct`) üç
şey olur: `reviews` satırı anında güncellenir, `review_corrections`'a
bir kayıt düşer (metin + eski/yeni karar + best-effort embedding), ve
bu kayıt üç ayrı tüketici tarafından "öğrenilir":

1. **Birebir override (exact override)** — `text_hash` eşleşmesi.
   Aynı normalize edilmiş metin bir daha gelirse, pipeline'a hiç
   girmeden son insan kararı uygulanır (`exact_lookup` /
   `latest_exact_correction`). O(1) sözlük — LLM çağrısı yok, maliyet
   sıfır. Batch job başında tenant'ın **son 10.000 düzeltmesi**
   `CorrectionStore` snapshot'ına yüklenir (bkz. §3, snapshot
   tazeliği sınırı).

2. **Few-shot enjeksiyonu** — Gemini birleşik sınıflandırma
   prompt'una (`analyze_batch_unified_async`) örnek olarak giren
   düzeltmeler. Bütçe `FEW_SHOT_LIMIT=12`: en güncel N/2 + (embedding
   varsa) chunk'ın merkezine anlamsal en yakın N/2
   (`merge_few_shot` — anlamsal öncelikli, dedup'lu birleştirme).

3. **RAG — anlamsal komşu arama** — pgvector cosine mesafesiyle
   (`ReviewCorrection.embedding`, HNSW indeks, `gemini-embedding-001`
   768-boyut). İki eşik: `NEAREST_MAX_DISTANCE=0.25` (few-shot adayı)
   ve **anlamsal doğrudan override** `SEMANTIC_OVERRIDE_MAX_DISTANCE
   =0.05` (Sprint 11.3 — birebir olmayan ama fiilen aynı şikayet
   olan yorumlar, "kargom 5 gündür gelmedi" ↔ "kargom 5 gündur
   gelmedi!", insan kararını devralır).

Üçü de **best-effort**: embedding API'si erişilemezse (anahtar yok,
zaman aşımı, hata) katman 2-3 sessizce devre dışı kalır, katman 1
(birebir) etkilenmez. Bu, sistemin tasarım gereği kademeli
bozulması — RAG hiçbir zaman analizi bloklamaz.

## 2. Ölçülen sınırlar (bugünkü kod, düzeltilmeden önce)

Dördü de gerçek — kod okumasıyla doğrulandı, tahmin değil. Bu bölüm
BİLİNÇLİ olarak düzeltme-öncesi anlık görüntü olarak kalıyor (başlık
"düzeltilmeden önce" diyor); her maddenin güncel durumu (uygulandı /
ertelendi) yanında işaretli, ayrıntı §3'te:

- **64-satır örnekleme — UYGULANDI (bu dalga, bkz. §3).**
  `_few_shot_for_chunk`, `sample = texts[:64]` — chunk 200 satır olsa
  bile (varsayılan `IMGA_BATCH_CHUNK_SIZE=200`) yalnız **ilk 64
  satır** embed edilip centroid'e girer. Chunk'ın geri kalan ~136
  satırı centroid'i hiç etkilemez; ilk 64 satır sektörel olarak
  "kargo" ağırlıklıysa, chunk'ın sonundaki "faturalama" satırları
  için centroid isabetsiz kalır.
- **Chunk-centroid few-shot, satır-bazlı değil — ERTELENDİ (core
  dondurulmuş, bkz. §5).** Anlamsal komşu arama (few-shot adayları)
  **chunk başına BİR KEZ**, tüm chunk'ın ortalama vektörüyle koşar —
  200 satırlık chunk'taki her satır AYNI few-shot setini görür. Bir
  chunk hem kargo hem faturalama şikayetleri karışık taşıyorsa,
  ortalama vektör ikisinin de ortasında bir yerde kalır ve hiçbirine
  gerçekten yakın olmayan örnekler seçilebilir. Not: bu dalganın
  düzeltmesi (yukarıdaki madde) centroid'in kapsadığı VERİYİ
  (64→tüm chunk) düzeltti, GRANÜLERLİĞİNİ (chunk→çağrı-başı)
  değiştirmedi — ikisi ayrı sorun, bkz. §5.
- **Manuel tek-analiz yolunda few-shot YOK — UYGULANDI (bu dalga,
  bkz. §3).** `routes/tenant_analyze.py` `pipeline.analyze` (klasik
  BERT+keyword/LLM hibrit) çağırır — `analyze_batch_unified_async`
  DEĞİL. Birebir + anlamsal-doğrudan-override (katman 1 ve RAG'ın
  override yarısı) çalışır (`_apply_manual_corrections`), ama katman
  2 (few-shot prompt enjeksiyonu) manuel analiz için hiç devrede
  değil — o yolun kendi sınıflandırıcısı zaten few-shot prompt şekli
  kullanmıyor.
- **Embedding tek sağlayıcıya (Gemini) bağımlı, opsiyonel değil
  bilinçli sabit.** `EMBEDDING_MODEL="gemini-embedding-001"`,
  `output_dimensionality=768`. Tenant'ın kazanan sağlayıcısı
  OpenRouter olsa BİLE embedding çağrısı Gemini'ye gider — RAG
  katmanı sağlayıcıdan bağımsız, ayrı bir alt sistem. Tenant'ın hiç
  Gemini anahtarı yoksa (yalnız OpenRouter kullanıyorsa) katman 2-3
  tamamen sessiz-NULL'a düşer; hiç hata yok, hiç uyarı yok, sadece
  RAG hiç çalışmaz. Bu maddenin kendisi bilinçli bir mimari karar
  (bkz. §4 "farklı sağlayıcı" satırı) — DÜZELTİLMEDİ, ama platform
  fallback anahtarı (§3, B3) tenant'ın hiç Gemini anahtarı olmama
  durumunu kapatıyor.

## 3. Bu dalgada yapılan hedefli müdahaleler (yeniden inşa DEĞİL)

İki ayrı görev paketinde yürüdü: B3 embedding fallback anahtarı +
skor/deneyim/perspektif kalıcılığını kapattı; B4 (bu paket) §2'nin
1. ve 3. maddelerini (kapsam örneklemesi + manuel yol few-shot
kapsaması) kapattı. Sırayla:

- **Kapsam düzeltmesi — chunk'ın TAMAMI embed edilir (B4).**
  `batch_analyzer._few_shot_for_chunk`, artık `texts[:64]` yerine
  yeni `_embed_chunk_rows` yardımcısını çağırıyor: chunk'ın TÜM
  satırları, `embed_texts`'in tek çağrıda kabul ettiği 64'lük API
  partileri hâlinde embed edilir (200 satırlık varsayılan chunk için
  ~4 parti). Centroid artık chunk'ın tamamının ortalaması; satır-
  bazlı anlamsal override araması (`semantic_override_lookup`, k=1)
  da her satırı kapsar — eskiden 65. satır ve sonrası bu aramaya hiç
  girmiyordu. Bir parti başarısız olursa TÜMÜ `None` döner (kısmi
  vektör listesiyle devam etmek hem centroid'i çarpıtır hem
  `semantic_hits`'in satır-index hizalamasını bozardı) — RAG'ın "ya
  tam kapsama ya da sessiz-fallback" best-effort ilkesiyle tutarlı.
  Maliyet notu: Gemini `embed_content` karakter başına ücretlendirir,
  LLM sınıflandırma çağrısına göre ihmal edilebilir ölçüde ucuz —
  200 satırlık chunk için ~4 embed çağrısı, önceki 64-satır
  kapsamasına göre marjinal ek maliyet. Per-LLM-çağrısı (25'lik
  parti) centroid granülerliği (§2'nin ikinci maddesi) BİLİNÇLİ
  ERTELENDİ — bkz. §5.
- **Manuel tek-analiz yoluna few-shot eklendi (B4).**
  `routes/tenant_analyze.py`'a `_build_manual_unified_context` +
  `_manual_few_shot` + `_classify_manual_analysis` eklendi:
  tenant'ın aktif LLM anahtarı varsa (batch worker'daki
  `_build_unified_context` ile aynı sözleşme, iş-ömürlü
  `WorkerContext` yerine tek bir istek-ömürlü `AsyncSession`
  üzerinden) `analyze_batch_unified_async([text], ...)` çağrılır —
  few-shot bağlamı, son `FEW_SHOT_LIMIT` düzeltme + (embed varsa)
  metnin KENDİ vektörüne `nearest_corrections(k=6)` (`merge_few_shot`
  ile birleştirilir, batch'teki desenle aynı). Motor kurulamazsa /
  düşerse / bayrak kapalıysa klasik `pipeline.analyze` (mevcut
  davranış) hiç değişmeden devreye girer — batch'in aksine BERT
  yedeği burada bayrakla asla KAPATILMAZ (tek etkileşimli istek,
  toplu işin OOM/sessiz-kalite-yayılması gerekçeleri geçerli değil).
  Few-shot aşamasında hesaplanan vektör, hemen ardından çalışan
  `_apply_manual_corrections`'ın anlamsal-override aramasına
  `precomputed_vector` olarak geçer — aynı metin için ikinci bir
  embed API çağrısı YAPILMAZ.
- **`tenant_analyze.py`'nin embed fallback-key engeli kaldırıldı
  (B4).** `_apply_manual_corrections`'taki eski `if not keys: return`
  erken çıkışı, tenant'ın Gemini anahtarı yokken `embed_text`'e HİÇ
  ulaşılmasını engelliyordu — bu da B3'ün platform
  `IMGA_EMBEDDING_FALLBACK_KEY`'inin bu yolda asla devreye
  giremeyeceği anlamına geliyordu (`embed_text` zaten boş `keys`
  listesiyle çağrılsa fallback kararını `_fallback_keys()` üzerinden
  kendi verir). Artık `embed_text(text, keys)` `keys` boş olsa bile
  çağrılıyor.
- **Manuel yolda düzeltme-kararı kalıcılığı tamamlandı (B4).**
  B3'ün `patch_analysis_with_decision` genişlemesi skor'u zaten
  taşıyordu; `experience_type`/`perspective_code` ise
  `AnalysisResult`'a giremediği için yalnız override izine
  yazılıyordu ve çağıranın (route) bunları decision nesnesinden
  DOĞRUDAN okuyup uygulaması gerekiyordu (bkz. `CorrectedDecision`
  docstring'i) — batch worker (B1) bunu `_apply_corrections`'ın
  `(analyses, correction_overrides)` dönüşüyle kapatmıştı, manuel yol
  açık kalmıştı. `_apply_manual_corrections` artık aynı imzayla
  `(analysis, decision | None)` döner; route, `decision.
  perspective_code`'u `record_and_decide`'a `perspective_override`
  olarak geçirir (LLM/heuristik tahmininin ÖNÜNE geçer, batch'teki
  öncelikle aynı) ve `decision.experience_type`'ı, business-dimension
  back-fill UPDATE'ine (`normalize_experience_type` üzerinden) bindirir
  — `record_and_decide`'ın kendisi deneyim kavramından habersiz,
  batch worker'ın kendi back-fill deseniyle aynı.
- **Embedding fallback anahtarı (B3)** — tenant'ın kendi Gemini anahtarı
  yoksa (`keys` boş), platform-seviyesi `IMGA_EMBEDDING_FALLBACK_KEY`
  ortam değişkeni doluysa onunla embed edilir
  (`services/embedding_service.py::_fallback_keys`). Tenant'ın
  Gemini anahtarları VARSA ama hepsi geçici olarak başarısızsa
  fallback DENENMEZ — o "geçici API hatası" farklı bir durumdur,
  "hiç anahtar yok" durumundan ayrı ele alınır (yanlışlıkla bir
  kotayı aşan tenant'ın trafiğini platform anahtarına kaydırmamak
  için). Anahtar yoksa davranış hiç değişmez — eski sessiz-NULL
  yolu korunur (§4'te veri-akışı tercihi detaylandırılıyor).
- **Skor/deneyim/perspektif düzeltmesinin kalıcılığı (B3, kod)** —
  `patch_analysis_with_decision`, kayıtlı `new_score` varsa AYNEN
  uygular (yoksa eski davranış: etiket→KB sabiti fallback). Önceden
  bir operatörün girdiği ince skor düzeltmesi (örn. -0.35), bir
  sonraki karşılaşmada etiketin kaba KB sabitine (-0.9) geri
  düşüyordu — düzeltme "yarım ölüyordu". `new_experience` /
  `new_perspective` de aynı prensiple `CorrectedDecision`'a taşınır;
  `AnalysisResult` pydantic modelinin bu iki kavram için alanı
  olmadığından (ve imga-core bu dalga donduruldu) bu ikisi doğrudan
  override izine (`OverrideHit.detail`) yazılır — Review satırına
  işlemek isteyen çağıranın `decision.experience_type` /
  `decision.perspective_code`'u kendi sink değişkenine uygulaması
  gereken bu sözleşme, artık HER İKİ tüketicide de (B1: batch
  worker'ın `_apply_corrections`/`_process_chunk`'ı; B4: manuel
  analiz route'unun `_apply_manual_corrections`'ı, yukarıda) kapalı —
  açık kalan tüketici yok.

## 4. Değerlendirilen alternatifler ve neden reddedildikleri

| Alternatif | Neden reddedildi |
|---|---|
| **Fine-tune** (tenant başına ya da genel bir modeli düzeltme verisiyle ince ayar) | Düzeltme hacmi tenant başına düşük (onlarca-yüzlerce satır) — fine-tune'un anlamlı sinyal üretmesi için gereken minimum örnek sayısının altında. Ayrıca her yeni düzeltme fine-tune'u geçersiz kılar (RAG'ın "anında öğrenme" özelliğini kaybederiz — düzeltme yapılır yapılmaz bir sonraki analizde etkili olması gerekiyor, günlük/haftalık fine-tune penceresi bu gecikmeyi kabul edilemez kılar). |
| **Rerank** (aday few-shot havuzunu ikinci bir modelle yeniden sırala) | Bugünkü darboğaz sıralama kalitesi değil, **kapsam** — 64 satırlık örneklem ve chunk-centroid zaten adayları daraltıyor. Rerank, zaten eksik/isabetsiz aday havuzunun sırasını iyileştirir ama havuzu büyütmez. Kapsam sorunu (§2) çözülmeden rerank marjinal fayda. |
| **Hibrit BM25 + vektör arama** | Düzeltme metinleri kısa müşteri şikayetleri — domain kelime dağarcığı dar, çoğu şikayet birbirine yakın kelimelerle ifade ediliyor ("kargo gelmedi" / "paket ulaşmadı" / "sipariş elime geçmedi"). BM25'in anahtar-kelime eşleşmesi bu eş-anlamlılığı YAKALAYAMAZ — tam da cosine-similarity'nin güçlü olduğu senaryo. Hibrit yaklaşımın ek karmaşıklığı (iki indeks, birleştirme skoru) bu domain'de BM25'in kazandıracağı marjinal faydayı karşılamıyor. |
| **Farklı embedding sağlayıcıları** (OpenRouter embedding, yerel embedding modeli, vb.) | **Sert engel, tercih değil**: `review_corrections.embedding` kolonu `gemini-embedding-001`/768-boyut HNSW indeksiyle üretildi. Farklı bir model FARKLI bir vektör uzayı üretir — aynı cosine-distance eşikleri (`0.25` / `0.05`) anlamsız hale gelir, mevcut indeksteki hiçbir satırla karşılaştırılamaz. Sağlayıcı değişimi = tam yeniden-embed (tüm `review_corrections` geçmişi) + eşiklerin sıfırdan kalibrasyonu. Bu maliyeti şu an haklı çıkaracak bir sinyal yok (Gemini embedding kalitesi gözlemlenen darboğazların NEDENİ değil — darboğaz örnekleme/centroid, §2). |

## 5. Neden mevcut pgvector + few-shot mimarisi korunuyor

Üç katmanın hiçbiri kavramsal olarak yanlış değil — ölçülen sınırlar
(§2) MİMARİ değil UYGULAMA darboğazları: örnekleme genişliği (64→200),
centroid granülerliği (chunk→çağrı-başı), ve tek bir tamamlayıcı veri
akışı (fallback anahtarı). Bunların hiçbiri pgvector'ü, HNSW indeksini
ya da üç-katman ayrımını sorgulamıyor. WS3'ün planlanan üç maddesinden
ikisi bu dalgada KAPANDI, biri ERTELENDİ:

1. **UYGULANDI (bu dalga, B4).** Chunk'ın **tüm satırları** embed
   edilir (64'lük API partileriyle, `_embed_chunk_rows`) — örnekleme
   sınırı kalktı. Bkz. §3.
2. **ERTELENDİ (core dondurulmuş).** Few-shot seçimini **çağrı
   başına** (25'lik parti centroid'i) indirmek —
   `GeminiUnifiedEngine.classify_unified_batch_async`'ın kendi
   `_call_batch_size`'a göre alt-partilere bölme mantığı imga-core
   içinde yaşıyor ve çağırana (worker/route) hangi satırın hangi alt-
   partiye düştüğünü bildirmiyor; bunu değiştirmeden granülerliği
   chunk'tan alt-partiye indirmek mümkün değil (few-shot listesi tüm
   çağrıya TEK parametre olarak geçiyor, per-parti değil). Bu, bu
   dalganın "core'a dokunulmaz" kısıtı altında yapılamaz — imga-core
   çözüldüğünde (gelecek dalga) `classify_unified_batch_async`'a
   parti-sınırlarını dışa veren bir out-param eklenip
   `_few_shot_for_chunk` o sınırlara göre alt-centroid hesaplayabilir.
   Kalıcı kazanım: madde 1'in düzeltmesi centroid'in kapsadığı VERİYİ
   (64→tüm chunk) düzeltti — granülerlik (chunk→çağrı-başı) hâlâ
   chunk-seviyesinde, bu maddenin kapsamı budur.
3. **UYGULANDI (bu dalga, B4).** Manuel tek-analiz yoluna da few-shot
   eklendi (k=6) — bugüne kadar hiç olmayan katman 2 kapsaması
   manuel yola da yayıldı. Bkz. §3.

Madde 1 ve 3 mevcut mimariyi YIKMADAN, aynı pgvector/HNSW/
CorrectionStore iskeleti üzerinde parametre + kapsam iyileştirmesi.
Yeniden inşa (farklı vektör DB, farklı embedding sağlayıcısı, rerank
katmanı, fine-tune) hiçbiri ölçülen darboğazı hedeflemiyor — mevcut
sınırların kök nedeni "yanlış mimari" değil "dar parametre" (§2'deki
dört madde de sabit sayı/sabit kapsam/sabit granülerlik sorunu,
mimari sorunu değil).

## 6. Fallback anahtar veri-akışı tercihi

`IMGA_EMBEDDING_FALLBACK_KEY` platform-seviyesi TEK bir Gemini API
anahtarı — tenant'ın kendi anahtarı yoksa devreye girer. Bilinçli
veri-akışı kararı, açıkça yazılıyor:

- **Ne anlama gelir:** yalnız-OpenRouter kullanan bir tenant'ın
  düzeltme metni (review text), o tenant hiç Gemini kullanmasa bile,
  RAG embedding'i için Google'ın Gemini API'sine gider. Sınıflandırma
  çağrısı OpenRouter'da kalır (tenant tercihi korunur); yalnız bu bir
  yardımcı alt-sistemin (embedding) veri yolu farklıdır.
- **Neden kabul edildi:** embedding modeli sağlayıcıdan tamamen
  ayrık bir seçim (§4, "farklı sağlayıcı" satırı) — HNSW uzayı zaten
  Gemini'ye kilitli. Fallback OLMADAN, OpenRouter-öncelikli tenant'lar
  RAG'ın üç katmanından ikisini (few-shot, anlamsal override) hiç
  görmüyor — düzeltme geri-beslemesi yalnızca birebir eşleşmeye
  düşüyor. Fallback bu boşluğu, sınıflandırma veri yolunu
  bozmadan kapatıyor.
- **Sınır:** fallback yalnız `keys` boşken devreye girer (§3) —
  tenant'ın kendi anahtarı geçiciyken bozulursa (rate limit, hatalı
  kota) trafiği platform anahtarına KAYDIRMAZ; o durumda düzeltme
  RAG'ı o istek için sessizce atlanır, tenant'ın kendi sorunuymuş
  gibi ele alınır. Bu, platform anahtarının maliyet/kota riskini
  sınırlı tutar.
- **Uygulanmazsa:** `IMGA_EMBEDDING_FALLBACK_KEY` tanımsız bırakılırsa
  davranış TAMAMEN eskisiyle aynı — sessiz-NULL. Bu bir opt-in
  platform kararı, kod yolunda zorunlu bir bağımlılık değil.

## Kaynaklar

- `packages/imga-api/src/imga_api/services/correction_store.py`
- `packages/imga-api/src/imga_api/services/embedding_service.py`
- `packages/imga-api/src/imga_api/services/correction_service.py`
- `packages/imga-api/src/imga_api/workers/batch_analyzer.py` (`_few_shot_for_chunk`, `_embed_chunk_rows`, `_apply_corrections`)
- `packages/imga-api/src/imga_api/routes/tenant_analyze.py` (`_apply_manual_corrections`, `_manual_few_shot`, `_build_manual_unified_context`, `_classify_manual_analysis`)
- `docs/analysis/2026-08-18-buyuk-paket-plan.md` (WS3 tasarım kararları)
