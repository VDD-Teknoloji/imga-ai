# Yapay Zeka Stack Kararı — TEK yöntem (2026-06-11)

Ürün sahibi talebi: "Sıfırdan kuruyormuş gibi düşün; tüm yapay zeka
işlemleri için EN OPTİMUM çözümü bul ve TEK yöntem olarak uygula.
Alternatif listesi istemiyorum. Gerekirse para harcarız."

## KARAR

**Tüm yapay zeka işlemleri tek sağlayıcıda toplanır: Google Gemini.
Görev katmanlı model ataması; tek istisna dayanıklılık yedeği
(Modal'daki BERT). Başka sağlayıcı (DeepSeek, OpenAI, self-host)
EKLENMEZ.**

| İşlem | Model | Çağrı şekli | Maliyet (bugün) |
|---|---|---|---|
| Sentiment + kategori (yorum başına) | `gemini-3-flash-preview` (env: `IMGA_UNIFIED_GEMINI_MODEL`) | 25 yorum/çağrı birleşik structured output + düzeltme few-shot | $0 (free tier + key rotasyonu) |
| SWOT üretimi | `gemini-3-flash-preview` | Agregat istatistik girdisi (ham yorum gitmez), tek çağrı | $0 |
| OKR üretimi | `gemini-3-flash-preview` | SWOT çıktısından, tek çağrı | $0 |
| Yönetici Özeti (briefing) | `gemini-3-flash-preview` | KPI delta + agregatlar, tek çağrı | $0 |
| Düzeltme embedding'leri (RAG) | `gemini-embedding-001` (768-dim) | Düzeltme başına 1 + chunk başına 1 (centroid) | $0 |
| Sentiment YEDEĞİ (Gemini erişilemezse) | BERT `savasy/bert-base-turkish-sentiment-cased` | Modal serverless CPU; o da yoksa lazy lokal | $0 (Modal $30/ay kredi içinde) |
| Kategori YEDEĞİ | Keyword lexicon | Lokal, deterministik | $0 |

Tek aile = tek hata sözlüğü, tek key rotasyonu, tek audit yolu, tek
kota yönetimi. Sprint 11.2 ile koddaki tüm kalıntı default'lar
(`gemini-2.5-flash`) bu aileye sabitlendi.

## Sıfırdan düşününce neden yine burası?

İhtiyaç profili: Türkçe ağırlıklı sınıflandırma + Türkçe iş metni
üretimi; ayda 50-250K satır; kurumsal alıcılar (THY, LCW ölçeği);
bütçe hassasiyeti var ama sıfır olmak zorunda değil; operasyonu tek
kişi yürütüyor (basitlik = değer).

1. **Türkçe kalite.** Sınıflandırmada flash sınıfı modeller Türkçe
   nüansı (ironi, karma duygu) BERT-base 2020 fine-tune'undan iyi
   yakalıyor; SWOT/OKR/briefing çıktıları doğrudan Türkçe kurumsal
   metin — Gemini'nin Türkçe üretimi bu segmentte en güçlülerden.
2. **Maliyet zaten ~sıfır ve büyüme yolu ucuz.** Free tier + key
   rotasyonu bugünkü hacmi taşıyor. Aşılırsa: tek projeye fatura
   bağla (Tier-1) — 250K satır/ay ≈ 30M giriş / 15M çıkış token ≈
   **ayda ~$10-30**. "Daha ucuz model" arayışının kazandıracağı şey
   ayda birkaç dolar; kaybettireceği şey ikinci entegrasyonun kalıcı
   bakım yükü.
3. **Operasyon yüzeyi.** Key rotasyonu, circuit breaker, audit,
   tenant-credential UI, structured-output parse — hepsi Gemini
   için kurulu ve testli. İkinci sağlayıcı bunların hepsini ikinci
   kez ister.
4. **Kurumsal satış optiği.** Hedef müşteri tedarik süreçlerinde
   "veriniz nereye gidiyor" sorusu kritik. Google Cloud cevabı
   savunulabilir; Çin merkezli sağlayıcı (DeepSeek) KVKK/tedarik
   görüşmesinde gereksiz sürtünme yaratır.

## Elenenler (kararlı, geri açılmayacak)

- **DeepSeek:** Ücretsiz katmanı yok (bizim taban maliyetimiz $0);
  Türkçe üretim kalitesi Gemini'nin altında; veri Çin merkezli
  sağlayıcıya gider (kurumsal satış riski); kazanç ayda birkaç
  dolar, bedel yeni entegrasyon + bakım. **Hayır.**
- **OpenAI / Claude:** Kalite iyi ama ücretsiz katman yok ve mevcut
  Gemini kalitesi görevler için yeterli — değişimin kazancı yok.
- **Self-host açık model (Modal GPU'da Qwen/Llama/Gemma):** Ayda
  ~$10-40 GPU + cold start + model ops; kalite flash'ın altında
  veya dengi. Kazanç yok. (Modal'ı GPU için değil, BERT yedeği
  CPU'su için kullanıyoruz — kredi içinde.)
- **BERT'i birincil tutmak:** Bu sunucu CPU'sunda ~1.4 sn/satır +
  kategori için zaten LLM gerekiyordu — iki sistemin maliyeti, tek
  LLM çağrısının işini yapıyordu. Yedek olarak değerli, birincil
  olarak değil.

## Bilinen tek açık konu — SWOT 504'leri

9.5.x'te SWOT üretiminde 504'ler görüldü ve "payload büyüklüğü"
sanılıyordu. Bu analizde netleşti: **SWOT girdisi zaten agregat**
(dağılımlar, NPS trendi — ham yorum gitmiyor), payload küçük.
504'ler model tarafı yavaşlığıydı (2.5-pro dönemi); 3-flash-preview
cutover'ından beri briefing temiz. Deploy sonrası SWOT yine 504
verirse teşhis LLM audit tablosundan okunacak (`/admin/llm-audit`,
duration_ms); çözüm o zaman çıktı budama/max_output_tokens olur —
sağlayıcı değişikliği DEĞİL.

## Operasyon notları

- Model id'leri env'den yönetilir: `IMGA_GEMINI_MODEL` (genel),
  `IMGA_UNIFIED_GEMINI_MODEL` (sınıflandırma override'ı). Yeni
  Gemini sürümü çıktığında: önce tek smoke çağrı, sonra env flip —
  kod değişikliği gerekmez (9.5.x cutover dersleri).
- Free tier kotası dolduğunda görülen davranış: unified classic'e
  düşer (BERT yedek) — sistem durmaz. Kalıcı çözüm: AI Studio'da
  tek projeye fatura bağla; key rotasyonu aynı kalır.
- Sınıflandırma için flash-lite sınıfı model (daha yüksek free RPM,
  daha ucuz) çıktığında: AI Studio'dan güncel model id doğrula →
  `IMGA_UNIFIED_GEMINI_MODEL` env flip. Kod hazır.
