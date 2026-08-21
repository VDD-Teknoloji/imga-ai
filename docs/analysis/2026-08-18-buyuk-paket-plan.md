# Büyük paket — plan ve durum (2026-08-18)

Kullanıcı isteği: onboarding + kuruma özel kategoriler, veri kalitesi
analizi, çalışan bazlı kalite, skor düzeltme + RAG revizyonu, dönem
karşılaştırma ekranı, Türkçe terim kalitesi, reviews filtreleri + hero
tıklama, Qwen3.8-27B benchmark. Subagent'lar Sonnet 5. Bu dosya
compaction'lara dayanıklı tek gerçek kaynak — her dalga sonunda DURUM
bölümünü güncelle.

## Sabitler

- Eval taban çizgisi (gold-500, canlı prompt, GLM 5.2): duygu .970,
  kategori .908 (belirsiz .022), bant .876 (komşu .996), deneyim .915.
  Eval kapısı: prompt/şema değişen her dalgada 4 eksen GERİLEMEMELİ.
  Kapı YENİ KOD İMAJIYLA koşar (test stack imajı veya yeni api imajı;
  --prompt-file yetmez çünkü q alanı şema+parse değişikliği).
- Deploy disiplini: commit → server pull → `set -e` build → `git log -1`
  ile HEAD doğrula. Patch-file kısayolu YOK (untracked dosya pull-abort
  tuzağı yaşandı).
- Qwen benchmark'ı hiçbir şeyi bloklamaz; sonuç raporlanır, varsayılan
  model DEĞİŞTİRİLMEZ (panel kararı kullanıcının).
- Migration'ların TEK SAHİBİ Dalga-1'deki migration ajanı; diğer hiçbir
  ajan alembic'e dokunmaz.

## Tasarım kararları (keşif + danışman düzeltmeleriyle)

### WS1 — Onboarding + kuruma özel kategoriler + terim sözlüğü
- Sınıflandırıcıya giden üst-seviye kod kümesi tenant-dinamik olur:
  etkin global kodlar (tenant_categories.is_enabled) + tenant'ın aktif
  custom Category kodları; `belirsiz` KOŞULSUZ her zaman kümede.
  _load_category_descriptions overlay'i zaten var; available_categories
  dinamikleşince A-sistemi (custom kategoriler) gerçekten devreye girer.
  Eval düzeneği 9-kod global sette KALIR (gold4 kıyaslanabilirliği).
  Not: disable-toggle'ın gerçekleşmesi davranış değişikliği; eski
  satırlar eski kodlarını korur.
- AI kategori önerisi: `POST /tenants/me/onboarding/suggest-categories`
  — girdi: industry + business_description (+ opsiyonel örnek yorumlar,
  son yüklemeden N satır). Çıktı: önerilen üst-kategori seti (kod/
  etiket/tanım+sınır kuralları), alt-taksonomi satırları
  (primary_category_code eşlemeli), kapatılması önerilen globaller
  (örn. hizmet firmasına urun_kalitesi). Kullanıcı seçer → apply
  endpoint'i custom Category + CategoryTaxonomy + toggle yazar.
- Onboarding: TenantCreateDialog çok adımlı olur: (1) temel, (2) profil
  (industry/company_size/business_description/terim sözlüğü) — create
  request'e alanlar eklenir, (3) AI kategori önerisi (atlanabilir),
  (4) davet linki. Mevcut kurumlar: /settings/taxonomies + profile
  sayfalarına "AI ile öner" akışı + eksik profil için banner.
- Partner API (`/v1/admin/tenants`) TenantService.create üzerinden
  geçirilir (bootstrap atlama bug'ı kapanır). Başka bir şey eklenmez.
- Terim sözlüğü: tenants.terminology (JSONB list[{term, note}]) —
  language_directive desenine paralel `terminology_directive(tenant)`
  SWOT/OKR/brifing/root-cause system prompt sonuna eklenir.

### WS2 — Veri kalitesi
- reviews.quality_flag String(16) NULL, CHECK IN
  ('duplicate','empty','informational','meaningless'). NULL = geçerli.
- duplicate: yazım anında decision==skipped_dedup'tan türetilir (intra
  + cross-batch). SQL backfill mümkün (eski satırlar).
- empty: artık Review satırı olarak YAZILIR — quality_flag='empty',
  s=NÖTR/0.0, c=belirsiz, decision yeni değer 'skipped_quality'.
  KRİTİK: boş metin hash'i dedup'a GİRMEZ (seen_hashes'e kaydetme,
  cross-batch dedup lookup atla, birebir düzeltme lookup atla) — yoksa
  ikinci boş satır 'duplicate' damgalanır. failed sayacına değil yeni
  quality sayaçlarına gider.
- informational/meaningless: TASARIM DEĞİŞTİ (2026-08-18, ölçüm
  sonucu): LLM prompt'una q alanı EKLENMEZ — iki kapı koşusu q'nun
  vergisini gösterdi (belirsiz .022→.044/.050; sıkılaştırma .058'e
  kötüleştirdi). Bunun yerine imga-api'de deterministik Türkçe
  heuristik modülü `services/data_quality.py`:
  classify_data_quality(text) -> None|'informational'|'meaningless'.
  informational: şablon/otomasyon kalıpları (değerli müşterimiz,
  bilgilendirme, doğrulama kodu, yola çıktı/teslim edildi kalıbı +
  birinci-tekil şikâyet işaretlerinin YOKLUĞU — precision öncelikli).
  meaningless: <=2 anlamlı sözcük / yalnız rakam-telefon-sipariş no /
  harf içermeyen. Kapsamlı unit test + gold NÖTR örnekleriyle spot
  doğrulama. Batch yazım yolunda + preview uyarılarında aynı modül.
- Analitik/rapor/heatmap: `include_flagged: bool = False` parametresi —
  4 bağımsız filtre yüzeyinin (analytics_service, report_service,
  heatmap_generator, review_list) hepsine; UI'da URL-state'li toggle
  ("Düşük kaliteli veriyi dahil et"). VARSAYILAN: HARİÇ. Not: backfill
  yeniden analizi sonrası tüm sayılar değişir — kapanış raporunda öne
  çıkar.
- Kalite raporu: batch job başına endpoint — bayrak sayıları, en çok
  tekrarlanan metinler (top-N + adet), çalışan bazlı kırılım, + TEK
  cached LLM özeti (neden tekrar/boş, öneriler) job satırında saklanır.
  UI: Step4Summary kartı + history tablosunda "Kalite Raporu" + ayrı
  panel.
- Çalışan kolonu: 5. business dimension `entered_by`
  (ck_tenant_business_dimensions_key CHECK genişler, _DIMENSION_KEYS +
  reviews.entered_by Text NULL) + smart-parser EmployeeNameDetector
  (öneri amaçlı). Çalışan bazlı kalite kırılımı kalite raporunda.
- Mevcut kırık: parse edilen `kaynak` DB'ye yazılmıyor → reviews.source
  Text NULL kolonu + yazım. (şablon vaadi tutulur)
- Eski 16.499 satır: q bayrağı için yeniden analiz gerekir (~$1-2,
  iz-yeniden-yazma düzeltmesi sonrası güvenli). Post-deploy adımı
  olarak planla; eski "Navlungo Test" kurumuyla birleştirilebilir.

### WS3 — Düzeltme + RAG
- CorrectReviewRequest: + sentiment_score [-1,1] (ops), +
  experience_type (ops), + perspective_code (ops, taxonomy kodu).
  ReviewCorrection'a new_score/new_experience/new_perspective NULL
  kolonları. Dialog: skor girişi (etikete göre ön-doldurma), deneyim ve
  alt-kategori seçimi.
- KRİTİK: patch_analysis_with_decision (birebir + anlamsal override)
  kayıtlı düzeltilmiş skoru/deneyimi/perspektifi UYGULAR — yoksa skor
  düzeltmesi ilk tekrar karşılaşmada ölür. SCORE_FOR_LABEL yalnız skor
  yoksa fallback.
- RAG iyileştirmeleri (yeniden inşa YOK, hedefli): (1) chunk'ın 200
  satırının TAMAMI embed edilir (64'lük API partileriyle); (2) few-shot
  seçimi chunk-centroid yerine LLM çağrısı başına (25'lik parti
  centroid'i); (3) manuel tek-analiz yoluna few-shot eklenir (k=6);
  (4) embedding fallback: platform-seviyesi Gemini anahtarı
  (IMGA_EMBEDDING_FALLBACK_KEY env) — AYNI MODEL ZORUNLU
  (gemini-embedding-001/768; farklı model HNSW uzayını bozar, OpenRouter
  embedding bu yüzden RED). Veri akışı bilinçli tercih olarak dokümante
  edilir. (5) Mimari analiz dokümanı: docs/analysis/…-rag-mimari.md.

### WS4 — Dönem karşılaştırma
- Yeni endpoint `/tenants/me/analytics/period-comparison`: iki pencere
  (a_from/a_to/b_from/b_to) tek istekte; metrikler: toplam, duygu
  dağılımı, kategori dağılımı, NPS özeti, deneyim dağılımı, ortalama
  skor; delta+yön. SINIRLAR AYRIK (brifingdeki date_from çift sayım
  hatası KOPYALANMAZ). include_flagged parametresi burada da.
- Sayfa /compare: iki dönem seçici (ay/hafta presetleri: "Nisan vs
  Mayıs", "geçen hafta vs bu hafta"), KpiCard delta kartları, yan yana
  grafikler. insights/page.tsx iskeleti + URL-state kuralı. Nav:
  Analitik bölümüne shell.nav.compare.

### WS5 — Reviews filtreleri + hero
- /reviews: duygu dropdown'ı (PerspectiveFilterDropdown eşdeğeri),
  tarih aralığı (date_from/date_to — kural dokümanına uyum), decisions
  + quality_flag filtresi, pill'lerin x'i TEK filtreyi kaldırır.
- ExecutiveHero SatisfactionBar segmentleri tıklanabilir →
  /reviews?sentiment_labels=X (+aktif dönem paramları).

### WS6 — Türkçe kalite
- SWOT/OKR/brifing/root-cause prompt'larına kural: "girdi verisindeki
  alan terimlerini birebir koru; eş anlamlıyla değiştirme" +
  terminology_directive (WS1 sözlüğü) enjeksiyonu.

### WS7 — Qwen3.8-27B benchmark
- qwen/qwen3.8-27b (in $0.45/M out $3.20/M; GLM 5.2 in $1.19/M out
  $3.74/M). 4 eksen + maliyet raporu; öneri sunulur, varsayılan
  değiştirilmez.

## Dalga planı (her dalga: yeşil süit + gerekli eval kapısı → deploy →
canlı kontrol → sonraki)

### Dalga 1 — temel (DB + core)  [DURUM: bekliyor]
- Ajan M (migration sahibi): tek zincir 0042+: reviews.quality_flag +
  entered_by + source; tenants.terminology; review_corrections
  new_score/new_experience/new_perspective; tenant_business_dimensions
  CHECK'e entered_by; analyze_batch_jobs kalite sayaçları
  (quality_duplicate/empty/informational/meaningless int + quality_summary
  JSONB NULL) + ReviewDecision'a skipped_quality. Model dosyaları dahil.
- Ajan C (core): unified_classifier q alanı (şema+prompt+parse+
  UnifiedPrediction.quality) + pipeline quality_sink + dinamik
  available_categories'i kabul eden imzalar (zaten parametre — yalnız
  belirsiz-garantisi utility). Testler.
- Eval kapısı: test stack imajıyla gold4 4 eksen (sunucuda).

### Dalga 2 — backend  [DURUM: bekliyor]
- Ajan B1: yazım yolu (batch_analyzer empty persist + hash istisnaları,
  quality sayaçları, entered_by/source yazımı, dinamik kategori kümesi
  _build_unified_context, sink bağlama) + kalite raporu endpoint'i +
  LLM özeti + preview heuristikleri.
- Ajan B2: analitik/rapor/heatmap include_flagged + period-comparison
  endpoint'i (ayrık sınır) + reviews listesi quality filtresi.
- Ajan B3: onboarding (create request profil alanları, suggest/apply
  endpoint'leri, partner API bootstrap fix) + terminology_directive +
  prompt terim kuralları + düzeltme genişletmeleri (skor/deneyim/
  perspektif + patch_analysis propagasyonu) + RAG iyileştirmeleri +
  rag-mimari dokümanı.
- Süit + eval kapısı (prompt değişti: q + terim kuralı) → deploy.

### Dalga 3 — frontend  [DURUM: bekliyor]
- Ajan F1: onboarding sihirbazı + settings AI-öner akışı + profil/
  sözlük UI.
- Ajan F2: kalite raporu UI + include_flagged toggle'ları (insights +
  dashboard) + reviews filtreleri + hero tıklama.
- Ajan F3: /compare sayfası + nav + i18n + düzeltme dialogu alanları.
- tsc + eslint + süit + deploy + tarayıcı doğrulaması.

### Kapanış
- Yeniden analiz (q backfill) önerisi/koşumu, Qwen raporu, memory,
  kapanış raporu (sayılar değişecek uyarısı dahil).

## DURUM GÜNCELLEMELERİ
(Yalnızca GERÇEKLEŞMİŞ olaylar yazılır; öngörü/tahmin yazılmaz.)
- 2026-08-18: Plan yazıldı. Keşif 4/4 tamam.
- 2026-08-18: Dalga 1: migration 0042 üretime uygulandı (b7ae887);
  süit 850 passed. q alanı denemesi ÖLÇÜMLE reddedildi: kapı 1
  .958/.902(belirsiz .044)/.886/.915; kapı 2 .970/.906(.050)/.888/.898;
  sıkılaştırma .956/.878(.058)/.882/.898 — q core'dan geri alındı
  (7aa8f2e), prompt bayt-bayt taban çizgisi. Kalıcı kazanımlar:
  0042 şeması, ensure_fallback_category, eval betiği --model/
  --call-batch-size/--concurrency. informational/meaningless artık
  Dalga 2'de heuristik modül olarak gelecek (WS2 güncellendi).
- 2026-08-18: Qwen3.8-27b: 3 koşu başarısız (1: muhakeme+240s aşımı;
  2: rate-limit; 3: parti 10 + eşz. 2'de dahi upstream "temporarily
  rate-limited" — AkashML 429 → Chutes 502). Model bugün OpenRouter
  sağlayıcılarında kapasite-aç. Kapanışta SON bir deneme yapılacak;
  yine düşerse rapor: operasyonel güvenilirlik FAIL, GLM 5.2 kalsın.
- 2026-08-18: Dalga 1 üretimde (7aa8f2e; api+worker healthy).
- 2026-08-18: Dalga 2 — Ajan B3 kod tarafı TAMAM (deploy/eval kapısı
  bekliyor, B1/B2 ile birlikte koşacak): admin tenant create + v1
  partner API bootstrap bug fix (kategori/taksonomi seed'i artık
  atlanmıyor) + onboarding_service.py/tenant_onboarding.py (suggest-
  categories: mock-provider'lı structured LLM çağrısı, imga-core
  donduğu için mevcut generate_root_cause ödünç alınıyor; apply-
  categories: tek transaction, tenant_config_service.
  create_taxonomy_entry ortak yardımcıya çıkarıldı — tenant_taxonomies.py
  POST da aynı yoldan geçiyor) + terminology_directive
  (strategic_constants.py) SWOT/OKR/brifing/root-cause'a bağlandı +
  4 prompt dosyasına terim-koruma kuralı + düzeltme genişlemesi
  (sentiment_score/experience_type/perspective_code, correction_
  service.py + correction_store.py: patch_analysis_with_decision
  artık kayıtlı new_score'u SCORE_FOR_LABEL yerine uyguluyor — hem
  birebir hem semantic yolda; experience/perspective AnalysisResult'a
  giremediği için (extra=forbid, imga-core donuk) OverrideHit.detail'e
  + CorrectedDecision alanlarına yazılıyor, batch_analyzer/
  tenant_analyze tüketicileri decision nesnesinden kendi sink'lerine
  uygulamalı — B1/B4 için açık sözleşme notu) + embedding fallback
  (IMGA_EMBEDDING_FALLBACK_KEY, yalnız tenant anahtarı YOKKEN devreye
  girer) + docs/analysis/2026-08-18-rag-mimari.md. Testler:
  test_review_corrections.py +7 (skor/deneyim/perspektif +
  patch propagasyonu), test_i18n_language_directive.py +3
  (terminology_directive), YENİ tests/test_onboarding.py (11 test) +
  docker-compose whitelist eklendi. ruff+mypy strict temiz (B3
  dosyaları); yerel pytest ortamı conftest import zincirinde ÖNCEDEN
  BOZUK (FastAPI/starlette sürüm uyuşmazlığı, main branch'te de var,
  B3 diff'inden bağımsız — DB'siz mantık ayrıca python -c ile elle
  doğrulandı). Kapsam dışı bırakılan/işaretlenen: terminology alanı
  yalnız tenant CREATE'te yazılabiliyor (tenant_profile.py PATCH'e
  eklenmedi — açık talimat yoktu); tenant_analyze.py'nin embed_text
  gate'i (`if not keys: return`) B4'ün dosyası, fallback anahtarını
  o yolda halen bloklar.
  Dalga 2 ajanları (B1/B2/B3) başlatıldı.
- 2026-08-18: Dalga 2 — Ajan B1 kod tarafı TAMAM (deploy/eval kapısı
  B1/B2/B3 ile birlikte bekliyor): YENİ services/data_quality.py
  (classify_data_quality — precision-öncelikli deterministik heuristik,
  veto seti kısa gerçek duygu sözcüklerini de korur) + batch_analyzer.py
  yazım yolu (boş metin artık Review olarak yazılır — quality_flag=
  'empty', decision=SKIPPED_QUALITY, seen_hashes'e girmez, tüm-boş
  chunk + BERT-çöküşü fallback yolu da dahil; intra+cross-batch
  duplicate quality_flag='duplicate' alır ve içerik-kalitesinin ÖNÜNE
  geçer; entered_by/source üç yazım noktasında da kalıcı; dinamik
  kategori kümesi _load_tenant_category_snapshot — etkin global+custom
  TEK sorguda, güvenli geri dönüş yalnız TOPLAM küme boşsa tetiklenir)
  + file_parser.py entered_by (5. dimension) + smart_parser
  EmployeeNameDetector (is_pii=False, bilinçli) + upload_validation.py
  informational/meaningless uyarıları + YENİ QualityReportService
  (batch_service.py: sayaç+top-tekrar+çalışan-kırılımı okuma +
  generate_root_cause vekili üzerinden TEK LLM özeti, cache'lenir;
  call_type='root_cause' ödünç alındı — CHECK constraint yeni değer
  kabul etmiyor, alembic'e dokunulmadı) + GET/POST
  /tenants/me/analyze/batch/{id}/quality-report(/generate) +
  BatchProgressSnapshot + BatchJobResponse kalite sayaçları.
  YAN DÜZELTME (B3 sözleşme notuna karşılık): _apply_corrections artık
  (analyses, correction_overrides) döner — batch_analyzer'ın per-satır
  döngüsü artık düzeltilmiş experience_type/perspective_code'u (insan
  kararı) LLM'in kendi tahmininin ÖNÜNE geçirerek uyguluyor (skor zaten
  patch_analysis_with_decision üzerinden akıyordu). İmza değişikliği
  reanalyzer.py + test_review_corrections.py çağrı yerlerine mekanik
  olarak yansıtıldı (davranışları değişmedi, yalnız tuple unpack).
  Testler: YENİ test_data_quality.py (35, lokal geçti), YENİ
  test_batch_quality.py (11, DB gerektirir), YENİ
  test_batch_quality_report.py (8, DB gerektirir), test_batch_upload.py
  1 test yeniden adlandırıldı+davranış güncellendi (boş satır artık
  failed değil), test_batch_sse.py/test_smart_parser.py/
  test_file_parser_dimensions.py/test_upload_validation.py genişletildi,
  test_review_corrections.py'ye 2 yeni birim testi + docker-compose
  whitelist'e 3 yeni dosya eklendi. ruff+mypy strict temiz (B1
  dosyaları, tam paket taramasıyla doğrulandı — kalan hatalar B2/B3
  WIP'i ya da önceden var olan ortam/lint-sürüm sapması, B1 diff'inden
  bağımsız). Yerel DB'siz testler (data_quality, smart_parser,
  file_parser, upload_validation, batch_sse snapshot) python -m pytest
  ile koşturuldu; DB gerektirenler sunucu süitine kaldı.
- 2026-08-18: Dalga 2 süiti İLK koşuda yeşil (951 passed, 2 skipped).
  Adversarial inceleme (5 mercek + doğrulayıcılar): 19 DOĞRULANMIŞ
  bulgu. Düzeltme dağılımı:
  FX1 (data_quality/batch_analyzer/reanalyzer): heuristik precision —
  "Beğenmedim"/"Hızlı kargo" meaningless, "teslim edildi... kutu boş"
  informational YANLIŞ pozitifleri; kural: yalnız KESİN çöp; correction
  _override varken heuristik atlanır; reanalyzer quality_flag yazar
  (backfill artık gerçek; duplicate korunur, empty satırlar adaylıktan
  çıkar) ve _correction_overrides tüketir (deneyim/perspektif insan
  kararı LLM'i ezer).
  FX2 (filtre + kapılar): quality_flag IS NULL 7 kalan yüzeye
  (tenant_executive, kpi_goals volume/manual-rate, root_cause bucket+
  sample, cohort, engagement, word_cloud kontrol) + tenant_reports
  request'ine include_flagged; custom-kategori kapıları dinamik
  (tenant_analytics:720, root_cause:195, tenant_taxonomies:77 → yeni
  services/category_codes.py ortak yardımcı).
  FX3 (manuel analiz + düzeltme + onboarding): LLM/embed transaction
  DIŞINA, 60s üst sınır + klasik fallback, perspective/experience
  sink'leri bağlanır + persist; kısmi düzeltme skoru sıfırlamaz;
  onboarding arşivli-kod çakışması temiz 400/409 (IntegrityError
  sızıntısı kapanır).
- 2026-08-18: FX1/FX2/FX3 düzeltmeleri tamam; süit yeşil (991 passed).
  Dalga 2 üretimde (2b2dc05 + 0043 migration; api+worker healthy).
- 2026-08-18: Dalga 3 (F1/F2A/F2B/F3 + skipped_quality entegrasyonu)
  üretimde (f734c3a; typecheck kapısı geçti, web healthy). Tarayıcı
  E2E doğrulaması KULLANICI GİRİŞİ bekliyor (oturum düşmüş; şifreyi
  ben giremem). Qwen son denemesi koşuda.
- 2026-08-18: Tarayıcı E2E turu tamamlandı (kullanıcı girişi sonrası):
  /compare (presetler+URL-state+delta kartları), reviews filtreleri +
  pill kaldırma, hero segment tıklaması, kalite raporu dialogu (gerçek
  tekrar metinleri + çalışan kırılımı), AI kategori önerisi uçtan uca
  (Navlungo için gumruk_evragi + hesap_yonetimi önerdi — UYGULANMADI,
  kullanıcı kararı), onboarding sihirbazı 3 adım. Yakalanan 2 kusur
  düzeltilip deploy edildi (9e3ccca): kalite özeti max_output_tokens
  2048→8192 (token sınırı hatası), dialog Select tetikleyicileri ham
  değer basıyordu → etiket eşleyicileri. Düzeltmeler canlıda yeniden
  doğrulandı (LLM değerlendirmesi üretildi, etiketler Türkçe).
- 2026-08-18: Qwen3.8-27b KARARI: 4/4 koşu sağlayıcı tarafı hatayla
  düştü (muhakeme+240s aşımları, upstream 429/502) — operasyonel FAIL,
  kalite ölçülemedi, GLM 5.2 kalıyor. Rapor:
  docs/benchmarks/2026-08-18-qwen38-27b.md.
- KALAN (kullanıcı onayı): q-backfill yeniden analizi (~$1-2, 16.499
  satırın informational/meaningless bayrakları + iz formatı tazelenir;
  reanalyzer artık quality_flag yazıyor) ± eski "Navlungo Test" kurumu
  (~26k satır, ~$8-9 toplam).
- 2026-08-20: Tarih vakası kökleri bulundu: (1) tarih tespiti yalnız
  başlık-adıyla, Kitap1 başlığı listede yoktu → 21.684 satır yükleme
  tarihine düştü; (2) dosya retention cron'unca silindi. Düzeltmeler
  üretimde (6a127e9): değer-tabanlı tespit + Step-2 açık tarih seçimi +
  no_date_column uyarısı + migration 0044 + backfill aracı
  (scripts/backfill_review_dates.py — KULLANICIDAN Kitap1.xlsx bekliyor)
  + retention artık terminal-olmayan işlerin dosyasını silmiyor.
- 2026-08-20: Süper-admin denetimi (19 bulgu/6 öneri) uygulandı
  (6a127e9 + 313ed4f, migration 0045): cost_usd + fiyat tablosu,
  /admin/usage + /admin/audit-logs + system-health, zengin Kurumlar
  listesi, prompt override kablolaması (root_cause/quality_report/
  onboarding_suggest artık gerçekten çalışıyor + whitelist 422),
  onboarding LLM çağrısı audit'e bağlandı, Karar Geçmişi'ne 4 aksiyon.
  Süit 1057 passed; tarayıcı doğrulaması yapıldı.
  Olay notu: paylaşılan ağaçta bir ajanın kapsamsız git stash'i geçici
  kayıp yarattı; dosya-dosya kurtarıldı, stash'ler doğrulama sonrası
  düşürüldü. Ders: paralel ajanlara "git stash KULLANMA" talimatı ekle.
- 2026-08-20: Ham dosya (Navlungo SLA raporu, 63 sütun) analiz edildi →
  docs/analysis/2026-08-20-navlungo-ham-veri-kolon-analizi.md. Tarih
  backfill'i ham dosyadan koşuldu: 16.500/16.500 hash eşleşti, %0
  uyuşmazlık (Nis 3.497 / May 3.407 / Haz 4.680 / Tem 4.916). Ayrıca 6
  boyut kolonu (entered_by/source/channel/business_segment/product_line/
  customer_tier) + insan kalite etiketleri geri dolduruldu: 10.378
  geçerli / 3.747 informational / 2.376 duplicate — sıfır LLM maliyeti.
  KVKK: TCKN/VKN, Kişi, Telefon kolonları İÇE ALINMADI. Navlungo tenant
  boyut konfigi (5 satır, display_label'lı) üretime uygulandı.
- 2026-08-20: Boyut analitiği dalgası (208d2c6) üretimde: İçgörüler'e
  "Boyutlar" sekmesi (boyut × metrik bar chart, kapsama satırı, tenant
  display_label tercihli), kohort kırılımına 6 iş boyutu, Analiz
  Arşivi'ne 6 boyut filtresi (dropdown + pill, URL-state, boş boyut
  gizlenir), GET /tenants/me/reviews/dimension-values ucu. Süit 1109
  passed. Tarayıcı doğrulandı: Temsilci·Yorum Sayısı (15 temsilci,
  kapsama %100), Entegratör Firma·Olumsuz Payı, kohort Temsilci trendi,
  reviews derin bağlantı (779 kayıt), /compare Nisan-Mayıs artık dolu.
  DAVRANIŞ DEĞİŞİKLİĞİ: boyut kırılımı varsayılan olarak işaretli
  (flagged) satırları HARİÇ tutar — "Düşük kaliteli veriyi dahil et"
  toggle'ı ile eski davranışa dönülür.
  Deploy olayı: test için tar'lanan dosyalar prod checkout'unu
  kirletti → pull sessiz iptal (boru tuzağı, yine); CRLF-only fark
  --ignore-cr-at-eol ile kanıtlanıp checkout -- ile temizlendi. Ders:
  test tar'ını prod ağacına DEĞİL ayrı bir dizine aç.
- 2026-08-21: Kolon-analizi yol haritasının ertelenen 1-5 maddeleri tek
  dalgada üretime alındı (162580f, migration 0046): review_facts yan
  tablosu + tenant_fact_mappings (13 alan, CSV başlık eşleme, Ayarlar
  UI'lı), fact_parsing (süre HH:MM:SS→dk, CSAT 10-değer, yer-tutucu
  kuralı: durum boş + süre 0 → NULL — ham veride %96,7 ölçümüyle
  gerekçeli), worker'da 4 persist yolunda otomatik alım, 3 analitik ucu
  (operations/summary + breakdown + sentiment-correlation; buckets
  metric_value — YENİ sözleşme, score hedge'i yok), İçgörüler "Operasyon"
  sekmesi (odim/ometric URL-state), review-detail Operasyonel Bilgiler
  kartı, backfill --fact yolu (chunk'lı upsert; asyncpg 32767-param
  sınırı adversarial incelemede yakalandı). Adversarial inceleme 3 ajan:
  5 doğrulanmış kusur düzeltildi. Süit 1193 passed. Navlungo backfill:
  16.500 facts satırı (SLA çözüm 15.492 / ilk yanıt 9.588 / CSAT 587 /
  efor 16.500 / teslimat 878 / tazmin 97); ham dosya kopyaları sunucudan
  ve konteynerden silindi (KVKK). Tarayıcı doğrulandı. İçgörü: CSAT 4-5
  verenlerin yalnız %0,3'ü metin-duygusunda POZİTİF (destek memnuniyeti
  ≠ metin içeriği — köprü tam bu farkı görünür kılıyor). Madde 6
  (Durum/Öncelik) BİLİNÇLİ dışarıda: IMGA ticket modülüyle çift kayıt +
  bayat yaşam-döngüsü anlık görüntüsü (%93,7 Resolved, %98 Low) — doğru
  yol Freshdesk API senkronu.
  Test-altyapı notu: sunucuda süit artık /opt/imga-test AYRI ağacında
  koşuyor (prod checkout kirlenmez); gitignore'lu test sırları
  (infra/imga/test/secrets/) klona elle kopyalanmalı.
- KALAN: q-backfill yeniden analizi (kullanıcı onayı, ~$1-2); eski
  "Navlungo Test" tenant'ının yeniden analizi (~$8-9, kullanıcı kararı);
  Freshdesk API senkronu (Durum/Öncelik dahil canlı yaşam döngüsü)
  uzun-vade adayı.
