# Eski İmga Sistemleri — Detaylı Özellik Analizi

**Tarih:** 2026-05-03
**Yazar:** local-agent (Claude Opus 4.7)
**Hedef:** Kullanıcı (özellik seçimi)
**Kapsam:** `cx_sentiment_dashboard/` ve `dedas_cx_sentiment_dashboard/` (her ikisi `.gitignore`'da, repo'ya commit edilmiyor — sadece referans)

> **Bu rapor, kullanıcı her özelliği tek tek "evet/hayır" seçip Sprint 8.3.5+ backlog'una alacak şekilde organize edildi.** Tenant-spesifik ayrımı yapılmadı (kullanıcı net dedi: hepsi generic). "Mevcut sistemde durumu" satırı her kartta — paritesi olan, kısmen olan, hiç olmayanlar net.

---

## 1. Mimari özet

### 1.1 `cx_sentiment_dashboard/` (daha yeni, geniş kapsamlı)

| Alan | Değer |
|---|---|
| Framework | Streamlit (single-page) |
| Ana dosya | `app.py` (1933 satır) |
| Yardımcı | `check_models.py`, `debug_*.py`, `download_logo.py`, `fix_csv.py`, `migrate_csv.py`, `reproduce_kb.py`, `test_*.py`, `verify_*.py` |
| Toplam Python satırı | ~2495 |
| Bağımlılıklar | streamlit, pandas, plotly, textblob, openpyxl, transformers, torch, google-generativeai |
| BERT modeli | `savasy/bert-base-turkish-sentiment-cased` |
| LLM | Gemini 2.5-flash (`google-generativeai`) |
| Veri kaynağı | xlsx/csv upload (sidebar file_uploader) |
| Persistans | `training_data.csv` (KB), `cx_rules.json` (smart rules), `cx_params.json` (SLA rules) — hepsi local file |
| Çıktı | Dashboard (Streamlit data_editor + Plotly charts), SWOT raporu (markdown), CSV append (KB) |
| State | `st.session_state` (in-memory, app restart'ta gider) |

### 1.2 `dedas_cx_sentiment_dashboard/` (önceki/customer-spesifik versiyon)

| Alan | Değer |
|---|---|
| Framework | Streamlit (aynı) |
| Ana dosya | `app.py` (1568 satır — 365 satır daha az) |
| Toplam Python satırı | ~1852 |
| Bağımlılıklar | aynı |
| BERT/LLM | aynı |
| Farklılıklar (cx'e göre eksik) | NPS, Monthly trend, KPI click-filter, custom branding, custom Gemini key UI, API rotation, Twitter intent, OKR, stats-injected SWOT, 23-cat heuristic, multi-cat sub-classification, Reset button, Debug expander |
| DEDAS'a özgü artılar | SLA day/hour/minute regex extraction (cx'te kayboluyor), Yunus Emre persona SWOT prompt'u, batch BERT optimizasyonu (`analyze_sentiment_bert_batch`) |

### 1.3 İki sistem arası özet

- **cx_sentiment_dashboard, dedas'ın gelişmişi** — DEDAŞ deployment'ı için fork edilen küçük sürüm sonradan büyütülmüş.
- DEDAS'ın **tek anlamlı katkısı**: SLA hour/minute regex (cx'te bu özellik regress'lenmiş, sadece "gün/iş günü/hafta" var; mevcut imga'ya da sadece gün geçmiş — F18 kartına bak).
- DEDAS'ın "Yunus Emre Ruhu" SWOT persona'sı bilinçli bir tercih (DEDAŞ stakeholder beklentisine göre); cx'te "Kıdemli CX Stratejisti" persona'sıyla değiştirilmiş — mevcut sistemde ikisi de yok.

---

## 2. Mevcut imga sistemi — referans paritesi

Ekleme/yenilik kartlarına geçmeden önce, eski sistemden yeni mimariye taşınmış olanlar:

| Modül | Yeri (yeni mimaride) | Durum |
|---|---|---|
| BERT pipeline | `imga-core/pipeline.py` | TAMAM |
| Customer perspective (8 cat) | `imga-core/perspectives.py:classify_customer_perspective` | TAMAM |
| Company perspective | `imga-core/perspectives.py:classify_company_perspective` | KISMEN — DEDAS'taki 4 cat versiyonu alındı, cx'teki 23 cat alınmadı (F8) |
| Yorum Özet (heuristic) | `imga-core/summary.py` | TAMAM (e-posta noise cleanup dahil) |
| Critical override | `imga-core/overrides/critical.py` | TAMAM |
| Tier1 sentiment override | `imga-core/overrides/tier1.py` | TAMAM |
| Strong Positive override | `imga-core/overrides/...` | TAMAM |
| SLA override | `imga-core/overrides/sla.py` | KISMEN — sadece gün/hafta, hour/minute yok, custom rule keyword desteği yok (F18) |
| Knowledge Base override | `imga-core/overrides/knowledge_base.py` (varsa) | KISMEN — runtime KB persistance var ama UI correction loop yok (F17) |
| Gemini hybrid classifier | `imga-core/classifiers/...` + `imga-core/llm/` | TAMAM (custom UI key + rotation hariç) |
| Risk Durumu | `imga-core/models.py:RiskClass` | TAMAM |

---

## 3. Özellik kataloğu

Toplam **35 özellik** kart olarak listelendi. Her kart bağımsız karar verilebilir; bağımlılık grafiği bölüm 5'te.

---

### Kart F1 — xlsx/csv upload + auto text-column detect

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:109-114`, `:1731-1738`
**Ne yapıyor:** Sidebar'da file_uploader; kullanıcı xlsx ya da csv yükler. Sistem dosyada şu kolonlardan birini arar: `Tweet İçeriği`, `Müşteri Yorumu`, `Review`, `review`, `comments`, `Yorum`. İlkini bulduğu hangisiyse onu metin kolonu kabul eder.
**UI/UX:** Sidebar'da tek buton + dosya seçici. Yükleme sonrası "✅ File Loaded" toast'ı ve `df.head(3)` preview.
**Mevcut sistemde durumu:** **VAR (kısmen) — `/analyze/upload` ekranında batch upload var (Sprint 8.3.1), ama text_column'u kullanıcı manuel seçiyor (otomatik bulma yok).**
**Karmaşıklık:** Küçük (1 gün)
**Bağımlılıklar:** Yok
**Mevcut mimariye uyum:** Doğal uyum — `BatchUploadForm` component'ine "auto-detect" toggle eklenebilir; bilinen kolon adlarını sırayla dener.
**Notlar:** Eski sistem ayrıca dosya değişikliğini `st.session_state['last_uploaded_file']` ile yakalayıp cache invalidate ediyor — yeni sistemde batch_id ayrı zaten, bu kısma gerek yok.

---

### Kart F2 — Date column auto-detection

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:849-872`
**Ne yapıyor:** Yüklenen dosyada `tarih`, `date`, `timestamp`, `zaman`, `created_at` kelimelerini içeren herhangi bir kolonu arar; bulamazsa object dtype kolonlarda heuristik dener (`-`, `/`, `.` separator + `pd.to_datetime` kabul). `df['Analyzed_Date']` olarak set eder; aylık trend grafikleri bu kolonu kullanır.
**UI/UX:** Sessiz — kullanıcı görmez. Eğer bulunursa Monthly NPS Trend chart'ı çalışır; bulamazsa "Insufficient date data" mesajı.
**Mevcut sistemde durumu:** YOK — yeni sistemde `analyzed_at` her zaman insert tarihi. Yüklenen dosyadaki gerçek olay tarihini ayrı bir kolon olarak saklamıyoruz.
**Karmaşıklık:** Orta (3 gün) — Review modeline `event_at: datetime | None` kolonu (migration), batch worker'ın CSV/xlsx parse aşamasında detect, /analyze single-call için manual override.
**Bağımlılıklar:** F31 (Monthly NPS trend) bu kolona bağımlı.
**Mevcut mimariye uyum:** Doğal uyum — Review tablosuna nullable timestamp ekleme, batch worker zaten satır-bazlı parse yapıyor.
**Notlar:** Eski sistemin "tek dosya, tek snapshot" mantığı yeni sistemde "her review ayrı satır, kümülatif arşiv" mantığına dönüşmüş — analytics endpoint'leri zaten `analyzed_at` ile tarih filtreliyor; `event_at` ayrı bir filtre boyutu olur ("müşterinin yorumu yazdığı tarih" vs "biz analiz ettik").

---

### Kart F3 — NPS column auto-detection + Detractor/Passive/Promoter

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:824-843`
**Ne yapıyor:** Dosyada `NPS`, `SCORE`, `PUAN`, `NET TAVSIYE SKORU`, `NET PROMOTER SCORE` kolonlarını arar. Bulduğunda her satırı 0-10 üzerinden segment'e mapler:
- 0-6: Kötüleyenler (Detractor)
- 7-8: Pasifler (Passive)
- 9-10: Destekçiler (Promoter)

NPS Score formülü: `(promoters - detractors) / total_responses * 100`.
**UI/UX:** Header altı "NPS Analysis" section: NPS Score büyük metrik, segment dağılım pivot tablosu (Count + Percentage).
**Mevcut sistemde durumu:** **YOK** — Review tablosunda NPS skoru yok; analytics endpoint'lerinde NPS aggregation yok.
**Karmaşıklık:** Orta (3-4 gün) — Review modeline `nps_score: int | None` (0-10), batch worker'ın CSV parse aşamasında auto-detect, /analyze single-call için optional input, `/tenants/me/analytics/nps-distribution` endpoint, /insights yeni "NPS" tab.
**Bağımlılıklar:** F31 (Monthly NPS trend) bağımlı.
**Mevcut mimariye uyum:** Doğal uyum — yeni alan + yeni endpoint + yeni tab. Bilinçli bir tasarım kararı: NPS sadece bazı tenant'larda anlamlı (B2C'de evet, B2B'de yok), ama generic olarak schema'da bulunması mantıklı.
**Notlar:** Sentiment ile NPS bağımsız sinyaller — NPS müşterinin kendi tahmini, sentiment metnin BERT yorumu. İkisini birlikte göstermek (NPS pasifi olan müşterinin yorumu negatif gelirse erken uyarı) çok güçlü bir analitik açıyor.

---

### Kart F4 — Source column for Twitter/X integration

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:1093-1098`, `:1156-1170`
**Ne yapıyor:** Yüklenen dosyada `Tweet URL`, `Tweet_URL`, `Tweet Link`, `Link`, `Link (Post URL)` kolonlarını arar. Stratejik Response feature'ında (F24) tweet ID'yi URL'den regex ile çıkarır (`status/(\d+)` pattern), Twitter intent URL'sine gömülür.
**UI/UX:** data_editor'da kolon olarak görünür; Strategic Response'da "🐦 Yanıtla (Doğrudan Tweet'e)" butonu üretir.
**Mevcut sistemde durumu:** **YOK** — Review modelinde source URL alanı yok.
**Karmaşıklık:** Küçük (1-2 gün) — Review modeline `source_url: str | None` ve `source_channel: str | None` (twitter, instagram, email, etc.). UI tarafı F24'e bağımlı.
**Bağımlılıklar:** F24 (Strategic Response). F4 olmadan F24 generic kalabilir; F4 ile F24 "doğrudan yanıtla" özelliği kazanır.
**Mevcut mimariye uyum:** Doğal uyum — Review tablosuna iki alan, batch worker auto-detect.
**Notlar:** Twitter intent URL public bir API; OAuth gerektirmez. Kullanıcı yanıtı ön-doldurulmuş bir tweet penceresinde görür, gönder/iptal kararı kullanıcıda — yasal olarak hassas durumlar için doğru tasarım.

---

### Kart F5 — Yorum Özet (heuristic emoji-prefixed concept tags)

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:469-540`, mevcut imga: `imga-core/summary.py`
**Ne yapıyor:** Metni temizledikten sonra (F6 e-posta noise cleanup) Tier 0 (Critical), Concept Mapping (İletişim Sorunu / İade Sorunu / Teslimat Gecikmesi), Tier 1 (Sentiment), Tier 2 (Issues), Tier 3 (Failures) sözlüklerinden bulunan kelimeleri toplayıp "📝 X, Y, Z, A" şeklinde özet üretir. Hiç eşleşme yoksa en uzun 4 kelimeyi alır.
**UI/UX:** data_editor'da "Yorum Özet" kolonu. Hızlı tarama için tasarlanmış — kullanıcı 1000 satırı tek tek okumadan dominant pattern'i görür.
**Mevcut sistemde durumu:** **VAR (TAM PARITE)** — `imga-core/summary.py` aynı logic, aynı sözlükler.
**Karmaşıklık:** -
**Bağımlılıklar:** -
**Mevcut mimariye uyum:** -
**Notlar:** Mevcut sistemde Review modelinin `summary` alanı bu çıktıyı tutuyor mu? Kontrol et — eğer `summary` Gemini-üretilen uzun metin için kullanılıyorsa Yorum Özet ayrı bir alan (`yorum_ozet: str` gibi) gerektirir. UI'da gösterilmediği için hiç doldurulmuyor olabilir.

---

### Kart F6 — Email noise cleanup regex set

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:472-491`, mevcut: `imga-core/summary.py`
**Ne yapıyor:** Yorum metninde "Sent from my iPhone", "On X wrote:", "From:", "Konu:", "Saygılarımızla", "İyi çalışmalar", "LC Waikiki Müşteri Hizmetleri", URL'ler, "MERHABALAR", "SAYIN YETKİLİ", "TEŞEKKÜRLER" gibi gürültüleri temizler. Header pattern'leri yerinde silinir (`re.sub`), footer pattern'leri ise eşleşme öncesi metinle kesilir.
**Mevcut sistemde durumu:** **VAR (TAM PARITE)** — `imga-core/summary.py:_EMAIL_NOISE_PATTERNS`.
**Notlar:** "LC Waikiki" string'i hardcoded — generic mimaride tenant-spesifik müşteri hizmetleri footer pattern'leri tenant config'e taşınmalı (ileride). Şu an hangi imzaları greplediği `summary.py`'de değişmez.

---

### Kart F7 — Customer Perspective (8 cat heuristic)

**Hangi sistemde:** Her ikisi (özdeş)
**Nerede:** `cx/app.py:543-559`, mevcut: `imga-core/perspectives.py:classify_customer_perspective`
**Mevcut sistemde durumu:** **VAR (TAM PARITE)**.

---

### Kart F8 — Company Perspective (23 cat heuristic, cx versiyonu)

**Hangi sistemde:** Sadece cx
**Nerede:** `cx/app.py:646-740` (95 satır, 23 if-elif zinciri)
**Ne yapıyor:** Kargom ulaşmadı / Deforme-Kırık Ürün / Özensiz Paketleme / Yanlış-Eksik Ürün / Ürünümde takım eksik / Ürün kalite (kumaş, dikiş) / İade Ücretim Hesaba Geçmedi / Kampanya Sorunları (Çark, Kazanıyorum) / E-bebek Para Aktarımı / Statü doğru değil / Sipariş iptal / Adres değiştir / Mağazadan iade / İadem ne durumda / İade nasıl yapılır / İade Süresi Aşımı / Üyelik ve Hesap / Fatura / Mağaza Sorunları / Ödeme + Kampanya / Genel ve Diğer (fallback). Her kategori 5-10 kelimelik liste eşleşmesi.
**UI/UX:** data_editor'da "Şirket Perspektifi" kolonu, ana stacked-bar chart'ta ana eksen.
**Mevcut sistemde durumu:** **YOK** — `imga-core/perspectives.py:classify_company_perspective` sadece DEDAS'ın 4 kategorili küçük versiyonunu içeriyor (Değişim Prosedürü / Omnichannel / Personel Davranışı / Lojistik / Hatalı Bilgilendirme / Genel Operasyonel Aksaklık).
**Karmaşıklık:** Orta (3-4 gün) — `imga-core/perspectives.py`'a yeni 23-cat fonksiyon (mevcut DEDAS-style'la birlikte ya da onu replace ederek). Yorum: pure Python, dependency yok, test yazımı kolay.
**Bağımlılıklar:** F12 (Smart Rules JSON) ile zenginleşir; ondan bağımsız da çalışır.
**Mevcut mimariye uyum:** Doğal uyum — `classify_company_perspective_v2(text, mode='detailed')` gibi. Eski 4-cat'i deprecate edip generic 23-cat'e geçmek de bir seçenek.
**Notlar:** Bu kategoriler `LCW`/`E-bebek` perakende odaklı görünüyor (örn. "kumaş", "kazak içeriği") ama ana sözlükler (kargo, iade, fatura, ödeme) generic. Sektör-spesifik kelimeler kullanıcının cx_rules.json gibi runtime extension'a taşıması (F12) için rezerv.

---

### Kart F9 — Experience Type (Dijital vs Operasyonel)

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:561-598`
**Ne yapıyor:** Metni `digital_variance` (app, mobil, web sitesi, sms, onay kodu, şifre, sistem hatası, sepet, buton, qr, karekod, ...) sözlüğüne karşı kontrol eder. Eşleşirse "Dijital Deneyim", aksi halde `operational_variance` (kargo, paket, mağaza, personel, ...) kontrol — eşleşme varsa "Operasyonel Deneyim", default da "Operasyonel Deneyim". KB override öncelikli (training_data.csv'da `Correct Experience` varsa o).
**UI/UX:** "Experience Breakdown" section'ında % kart (Dijital/Operasyonel), her ikisi click-to-filter button (F32). data_editor'da "Deneyim Tipi" kolonu.
**Mevcut sistemde durumu:** **YOK** — yeni mimaride experience type alanı yok.
**Karmaşıklık:** Küçük-orta (2-3 gün) — Review tablosuna `experience_type: str | None` (`dijital`|`operasyonel`), `imga-core` içine yeni classifier modülü, `/insights`'a yeni "Deneyim Tipi" tab veya mevcut Cross-Analysis tab'a yeni bir matrix.
**Bağımlılıklar:** F10 (Op alt-cat) + F11 (Dij alt-cat) bu sınıflandırmaya bağımlı; F32 (KPI cards) ve F35 (chart filter) UI bağımlılığı.
**Mevcut mimariye uyum:** Doğal uyum — eklenmesi mekanik. Tek dikkat: experience type ile primary category (kargo/iade/fatura) ortogonal değil; örneğin "kargo" kategorisi her zaman operasyonel. Bunu yansıtan basit bir heuristik (primary category'den derive et) muhtemelen yeterli; ayrı kolon gerekmez.

---

### Kart F10 — Operational Sub-category (Kargo/Depo/Mağaza/Çağrı)

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:600-621`
**Ne yapıyor:** Sadece `Deneyim Tipi == "Operasyonel Deneyim"` olan satırlar için 4 alt kategori:
1. **Kargo / Lojistik** — kargo, kurye, teslimat, dağıtım, gelmedi, yurtiçi, aras, mng, sürat, ptt, takip
2. **Depo / Ürün Kalitesi** — yanlış ürün, eksik, defo, yırtık, leke, paketleme, etiket, beden yanlış, kirli, tüylendi, kalitesiz
3. **Mağaza Deneyimi** — mağaza, şube, kasa, kabin, personel, çalışan, reyon, güvenlik, avm
4. **Çağrı Merkezi** — müşteri hizmetleri, temsilci, telefona, ulaşamıyorum, bağlan, sesli yanıt, 0850

**Mevcut sistemde durumu:** **YOK**
**Karmaşıklık:** Küçük (1 gün) — F9 yapılırsa bu da gelir (aynı sınıflandırıcı modülü).
**Bağımlılıklar:** F9.

---

### Kart F11 — Digital Sub-category (Teknik Arıza vs Eksik Özellik)

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:623-644`
**Ne yapıyor:** Sadece dijital satırlar için:
1. **Eksik Özellik** — yok, olmalı, eklenmeli, bulamadım, seçeneği yok, yapılamıyor, değiştiremiyorum, koymamışlar, göremiyorum, silinmiyor, adres değiştiremiyorum, kart silemiyorum
2. **Teknik Arıza** — hata, error, donuyor, açılmıyor, giriş yapamıyorum, kod gelmiyor, sms gelmiyor, şifremi kabul etmiyor, yüklenmiyor, 404, server, bağlantı, atıyor, kapanıyor, bozuk, çalışmıyor, sayfa beyaz, bug (default)

**Mevcut sistemde durumu:** **YOK**
**Karmaşıklık:** Küçük (1 gün)
**Bağımlılıklar:** F9.

---

### Kart F12 — Smart Rules JSON runtime extension

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:347-358` (`load_rules`/`save_rules`), `cx/cx_rules.json` (boş, kullanıcı dolduracak)
**Ne yapıyor:** Şema:
```json
{
  "customer_rules": [
    { "label": "İade Talebi", "keywords": ["iade", "geri al"] }
  ],
  "company_rules": [
    { "label": "Lojistik / Kargo Firması Hatası", "keywords": ["aras", "sürat"] }
  ]
}
```
Eski sistemde her perspective sınıflandırıcısı **önce** bu listeyi kontrol ediyor, sonra hardcoded. UI tarafında bu rules'ları düzenlemek için form yok (kullanıcı dosyayı manuel ediyor) — sadece runtime read/save var.
**Mevcut sistemde durumu:** **YOK** — yeni mimari yorumunda "Smart-Rules JSON engine (cx_rules.json) is intentionally omitted from this sprint" yazıyor (`imga-core/perspectives.py:5`).
**Karmaşıklık:** Orta (3-4 gün) — `tenant_config` JSONB'sine `customer_rules` + `company_rules` array'i (multi-tenant per-tenant), `imga-core/perspectives.py`'a runtime injection, /settings tarafına UI form.
**Bağımlılıklar:** F7 + F8'i extends ediyor. Tek başına ise: kullanıcının "yetersiz değil 'kalitesiz'" kelimesiyle eşleşmesini istemediği bir durumu kapatması için hızlı çözüm.
**Mevcut mimariye uyum:** Doğal uyum — TenantConfig zaten JSONB pattern'inde; yeni alan eklemek mekanik.
**Notlar:** Generic özellik — her tenant kendi sözcüklerini ekler. Kullanıcının "tenant-spesifik bir şey yok" demesiyle kısmen çelişir gibi gözüküyor ama bu **özellik** generic, **veri** her tenant için ayrı; bu sağlıklı.

---

### Kart F13 — BERT base sentiment (savasy/bert-base-turkish-sentiment-cased)

**Hangi sistemde:** Her ikisi
**Mevcut sistemde durumu:** **VAR (TAM PARITE)** — `imga-core/pipeline.py`.

---

### Kart F14 — Strong Positive Words override

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:994-1003`
**Ne yapıyor:** TIER1_POSITIVE listesi (teşekkür, harika, süper, memnun, başarılı, hızlı, güzel, kaliteli, beğendim, mükemmel, iyi, sağlam, eksiksiz, tavsiye, efsane, muhteşem, bayıldım) eşleşirse `Sentiment_Score = 0.90`, label = "Pozitif".
**Mevcut sistemde durumu:** **VAR (TAM PARITE)**.

---

### Kart F15 — Critical Keywords override

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:1005-1013`
**Ne yapıyor:** CRITICAL_KEYWORDS (hırsızlık, hırsız, suçlama, alarm, polis, mahkeme, dava, savcılık, tehdit, taciz, hakaret, küfür, güvenlik, etiket, unutulmuş, böcek) → `Sentiment_Score = -0.95`, "Negatif".
**Mevcut sistemde durumu:** **VAR (TAM PARITE)**.

---

### Kart F16 — Tier1 Negative Words override

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:1015-1022`
**Ne yapıyor:** TIER1_SENTIMENT (ilgisiz, saygısız, kaba, çözümsüz, mağdur, rezalet, berbat, iğrenç, profesyonellikten uzak, lakayıt, bilgisiz, yetersiz, sorumsuz, dalga geçer gibi, oyalayıcı, ezbere, küstah, yalancı, fiyasko, alaya, aptal, dalga) → `-0.75`, "Negatif".
**Mevcut sistemde durumu:** **VAR (TAM PARITE)**.

---

### Kart F17 — Knowledge Base override (training_data.csv) + UI correction loop

**Hangi sistemde:** Her ikisi (KB), sadece cx (UI loop)
**Nerede (KB read):** `cx/app.py:181-211` `load_knowledge_base()`, mevcut: imga'da KB hooks var
**Nerede (UI correction loop):** `cx/app.py:1209-1264`
**Ne yapıyor (KB):** `training_data.csv` schema: `Review, Correct Label, Correct Experience, Reason, Timestamp`. Her load'da `kb_dict` (text → {label, experience}). Score'u güçlü override eder (0.95 / -0.95).
**Ne yapıyor (UI loop):** Dashboard'daki data_editor'da her satırın yanında "Fix This" checkbox'ı. İşaretli satırlar yeni bir editor'da açılır:
- Mevcut tahmin (read-only)
- "Best Label" (Pozitif/Nötr/Negatif dropdown)
- "Best Experience" (Dijital/Operasyonel dropdown)
- "Reason" (free text, opsiyonel)

"🚀 Train & Save" butonu CSV'ye append, cache temizle, rerun.
**Mevcut sistemde durumu:**
- KB read: **VAR** (`imga-core` içinde knowledge_base override layer).
- UI correction loop: **YOK** — yeni sistemde "bunu yanlış sınıflandırdı" diye düzeltme arayüzü yok. /reviews/[id]'de manuel ticket promote var ama label düzeltme yok.

**Karmaşıklık:** Orta (3-5 gün) — `/reviews/[id]` veya `/reviews` listesine "Düzelt" butonu, yeni endpoint `POST /tenants/me/reviews/{id}/correct-label`, KB tablosu (review_corrections) ya da Review tablosuna `corrected_label`/`corrected_by_user_id` kolonları, KB override layer'ın bu kolonları okuması.
**Bağımlılıklar:** F17'nin UI loop kısmı F36-F37'ye yakın — ikisi birlikte yapılırsa daha düzgün.
**Mevcut mimariye uyum:** Doğal uyum — multi-tenant zaten Review tablosunda, audit trail mekanizması var. Düzeltme = audit-loglu update.
**Notlar:** Özellikle önemli — production'da kullanıcının modelin yanlışlarını eğitebilmesi tek başına bir milestone. Eski sistemde tek-kullanıcı CSV vardı; çok-tenantta ya **per-tenant KB** (her tenant kendi düzeltmelerini etkiler) ya da **global KB** (admin kanalı düzeltmesi tüm tenantları etkiler). Per-tenant daha güvenli, generic.

---

### Kart F18 — SLA day/hour/minute regex extraction + custom rule keywords

**Hangi sistemde:** DEDAS (cx'te day-only)
**Nerede (DEDAS):** `dedas/app.py` (BERT post-process loop, `day_match`, `hour_match`, `min_match` regex'leri)
**Ne yapıyor:** Metinde `(\d+) gün|iş günü|hafta` (gün), `(\d+) saat` (hour), `(\d+) dakika` (min) çekildikten sonra `cx_params.json:sla_rules` listesine bakar:
```json
{"sla_rules": [
  {"name": "Depo Hazırlık", "keywords": ["hazırlanıyor", "depo", "paket", ...], "limit": 2, "unit": "Gün"},
  {"name": "Kargo Süresi", "keywords": ["kargo", "teslimat", ...], "limit": 3, "unit": "Gün"}
]}
```
Anahtar kelime eşleşmesi + birim eşleşmesi varsa kuralı uygular (`days <= limit` → 0.05 Pozitif, aksi → -0.60 Negatif).
**Mevcut sistemde durumu:** **KISMEN** — `imga-core/overrides/sla.py` sadece gün/hafta extract ediyor, hour/minute yok. Kuralları hardcoded `SLA_SHIPPING_CONTEXT_KEYWORDS` + `SLA_WAREHOUSE_CONTEXT_KEYWORDS` (2 sabit context). Custom keyword listesi ya da limit yok; tenant config'ten gelmiyor.
**Karmaşıklık:** Orta (3-5 gün) — `imga-core/overrides/sla.py`'a hour/minute regex extension, `tenant_config.sla_rules` JSONB alanı (multi-tenant), config'ten gelen rule list'le çalışan apply fonksiyonu, /settings'e UI form (rule add/remove).
**Bağımlılıklar:** F12 (Smart Rules JSON) ile aynı UI altında konumlanabilir.
**Mevcut mimariye uyum:** Doğal uyum — override system zaten OverrideHit dönen modüler yapıda.
**Notlar:** "Kargo 3 günde gelmeli" tenant A için, "Kargo 5 günde gelmeli" tenant B için — generic ihtiyaç. Hour/minute "Çağrı 10 dakikada cevaplanmalı" gibi senaryolarda anlamlı (call center SLA'leri).

---

### Kart F19 — Tier2 Issue check (BERT post-fallback)

**Hangi sistemde:** DEDAS (yalnızca)
**Nerede:** `dedas/app.py` BERT post-process — eğer SLA override etmediyse ve BERT skoru `> -0.05` (yani pozitif/nötr) iken metinde TIER2_ISSUES kelimesi (iade, iptal, ücret, para, teslimat, kargo, gecikme, bozuk, defolu, eksik, yanlış, sahte, hile, yalan, ...) varsa skoru `-0.40` Negatif yapar.
**Ne yapıyor (kavramsal):** "BERT bunu negatif görmüyor ama metin operasyonel sıkıntı içeriyor — yine de işaretle". Yumuşak bir override.
**Mevcut sistemde durumu:** **YOK** — mevcut overrides'da Tier2 yok. Sadece Tier1 (negative adjective) var.
**Karmaşıklık:** Küçük (1 gün) — yeni override modülü `imga-core/overrides/tier2.py`. Score etkisi yumuşak (-0.40), Tier1 (-0.75) ve Critical (-0.95) ile çakışmaz.
**Bağımlılıklar:** Yok.
**Mevcut mimariye uyum:** Doğal uyum — override registry'ye yeni katman ekleme. Sprint 8.3.4'le birlikte override layer trace UI'sinde otomatik görünür (Tier2 chip'i).
**Notlar:** Kullanıcı bu özelliği isterse override hierarchy 6 katmana çıkar: Strong Positive → Critical → Tier1 → SLA → Tier2 → KB. Sıralama (precedence) Sprint spec'inde netleşmeli.

---

### Kart F20 — Risk Durumu (basit ikili sınıflandırıcı)

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:981-986`
**Ne yapıyor:** `if Sentiment_Score < -0.05 → "🔴 Negatif" else "🟢 Risk Yok"`. data_editor'da kolon olarak görünür.
**Mevcut sistemde durumu:** **VAR** — `imga-core/models.py:RiskClass` ve `imga-core/pipeline.py`'da hesaplanıyor. UI'da gösteriliyor mu kontrol etmek lazım — büyük ihtimalle ikincil bir alan, /reviews list'te görünmeyebilir.

---

### Kart F21 — Gemini hybrid classifier toggle

**Hangi sistemde:** Her ikisi
**Mevcut sistemde durumu:** **VAR (TAM PARITE)** — `imga-core/classifiers/`. Toggle mevcut ortam değişkenleriyle.

---

### Kart F22 — SWOT analysis via Gemini (with stats injection)

**Hangi sistemde:** Her ikisi (cx'te stats-injected, DEDAS'ta saf metin)
**Nerede:** `cx/app.py:379-427`, dashboard'da Tab 2: SWOT
**Ne yapıyor:** Tüm yorumları (max 100K karakter trunc) Gemini'ye gönderir. cx versiyonu prompt'a stats'ı da ekler:
```
Toplam Analiz Edilen Yorum: 9699
Negatif Memnuniyet Oranı: %23.5
Pozitif Memnuniyet Oranı: %58.2
En Çok Şikayet Edilen Konular (Negatif İçinde):
- Kargom ulaşmadı: %30.2
- İade nasıl yapılır: %12.8
```
Gemini'ye "Tavsiyelerini bu rakamlarla destekle, hayali rakam uydurma" der. Output 5 bölüm: Güçlü/Zayıf/Fırsatlar/Tehditler/Stratejik Tavsiye.
**UI/UX:** Tab 2'de "🚀 Generate SWOT" butonu, sonuç markdown render. Tutorial: tek seferlik analiz, sonuç session_state'te tutuluyor.
**Mevcut sistemde durumu:** **YOK** — yeni mimaride SWOT raporu yok; report generator (Sprint 8.3.2) sadece Excel multi-sheet üretiyor, narrative analysis yok.
**Karmaşıklık:** Orta (3-5 gün) — Backend: yeni endpoint `POST /tenants/me/insights/swot` (filter accept eder, Gemini call yapıp markdown döner; expensive olduğu için job-based async pattern - report generator gibi). Frontend: /insights'a yeni "SWOT" tab veya separate /reports/swot route.
**Bağımlılıklar:** F23 (OKR) bağımlı.
**Mevcut mimariye uyum:** Doğal uyum — `imga-core/llm` zaten Gemini provider'a sahip. Yeni service `swot_service.py`, async job pattern (report_generator gibi).
**Notlar:** Stats injection + "rakamla destekle" talimatı çok değerli — LLM'in halüsinasyon yapmasını eyleme dökecek bir tasarım. Generic özellik.

---

### Kart F23 — OKR generation from SWOT

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:1838-1928`
**Ne yapıyor:** SWOT raporu üretildikten sonra "🚀 OKR'ye Gönder" butonu. Kullanıcı:
1. **Yıllık** (Annual) veya **Çeyreklik** (Quarterly) bağlam seçer.
2. Sistem SWOT'tan "Stratejik Tavsiye" başlığı altındaki maddeleri regex ile çıkarır (madde işareti `-`, `*`, `1.`, `•`, `>` ile başlayan, indent <2 olan satırlar).
3. Çeyreklik seçilirse 1. tavsiyeyi otomatik Amaç (Objective) olarak yerleştirir, kullanıcı düzenleyebilir.
4. "➕ Tüm Tavsiyeleri Amaç Olarak Ekle" tüm bullets'ı Amaç slot'larına atar.
5. Manuel "Tek Satır Ekle" alternative.

Sonuç: editlenebilir Amaç listesi (text input array). KR (Key Results) eklemiyor — sadece O kısmı.
**Mevcut sistemde durumu:** **YOK**
**Karmaşıklık:** Küçük (1-2 gün) — F22 yapıldıktan sonra sadece UI: SWOT sayfasında "OKR'ye dönüştür" butonu, recommendations regex extract, list editor.
**Bağımlılıklar:** F22.
**Mevcut mimariye uyum:** Doğal uyum — pure UI ve metin parse, backend store gerekiyorsa basit JSONB.
**Notlar:** Eski sistemde OKR'leri saklayıp izlemek yok (sadece generate). Sürekliliğin getirilmesi (kayıt + zaman içinde takip) ek karmaşıklık ama kullanıcı isterse F23+ olarak ekleme.

---

### Kart F24 — Strategic Response per row (Twitter 280-char + intent URL)

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:218-272` (`analyze_strategic_response`), `cx/app.py:1117-1206` (UI)
**Ne yapıyor:** data_editor'da her satırın yanında "✨ Analiz Et & Yanıtla" checkbox'ı. İşaretli satırlar tıklanırsa Gemini'ye spesifik bir prompt gider:
```
Sen şikayetin muhatabı kurumun 'İmga' isimli kurumsal AI asistanısın.
Müşteri Şikayeti: "{text}"
Görevin:
1. Seviye (1-4)
2. Duygu durumu
3. Profesyonel, empatik, çözüm odaklı yanıt taslağı (Maks 280 karakter — Twitter sınırı)
4. Strateji (DM yönlendir / Hemen ara / Standart prosedür)
```

Output:
- Level kartı (Level 1-4)
- Sentiment kartı
- Strategy kartı
- Suggested Response (text_area, 150 px)
- Karakter sayısı counter (✅/<280, ⚠️ aşıyor)
- "🐦 Yanıtla" butonu (Twitter intent URL):
  - Tweet ID varsa: `x.com/intent/tweet?text=...&in_reply_to=ID`
  - Yoksa: `x.com/intent/tweet?text=...`

**Mevcut sistemde durumu:** **YOK** — yeni mimaride per-row AI yanıt üretme yok. /analyze'da Gemini sentiment+kategori yapıyor ama "yanıt taslağı" üretmiyor.
**Karmaşıklık:** Orta (3-5 gün) — Backend: yeni endpoint `POST /tenants/me/reviews/{id}/strategic-response` (Gemini call). Frontend: /reviews/[id]'de "Yanıt Taslağı Üret" butonu, sonuç gösterimi, karakter counter, Twitter intent URL (F4 ile entegre eğer source_url var). Bonus: 280 sınırı opsiyonel (tenant config — Twitter mı, Email mı kullanıyor).
**Bağımlılıklar:** F4 (Source URL Twitter integration için, opsiyonel).
**Mevcut mimariye uyum:** Doğal uyum.
**Notlar:** Twitter intent URL public — OAuth gerekmez, kullanıcının yanıtı göndermeden onaylaması gerekir (yasal güvenlik). Generic özellik — Twitter dışında Email taslağı, SMS, Instagram DM template'i de aynı pattern.

---

### Kart F25 — Tweet ID extraction from URL (F4 + F24 destekçisi)

**Hangi sistemde:** cx
**Nerede:** `cx/app.py:1156-1170`
**Ne yapıyor:** `Tweet URL` kolonundan veya raw text'ten `status/(\d+)` regex'iyle Tweet ID çeker. Sadece raw integer ise onu kullanır.
**Mevcut sistemde durumu:** **YOK**
**Karmaşıklık:** Çok küçük (½ gün) — F4 yapılırsa parse helper'ı bedava.
**Bağımlılıklar:** F4 + F24.

---

### Kart F26 — Custom Gemini API Key in sidebar

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:317-324`
**Ne yapıyor:** Sidebar'da "🔑 Custom Gemini API Key (Optional)" text_input (type=password). Kullanıcı kendi key'ini girebilir; öncelik bu key'de, fallback `gemini_key.txt`. Kullanım amacı: shared file key quota dolduğunda kullanıcı kendi key'iyle devam eder.
**Mevcut sistemde durumu:** **YOK** — multi-tenant'ta key yönetimi env variable'la (IMGA_GEMINI_API_KEY) yapılıyor; tenant başına özel key yok.
**Karmaşıklık:** Orta (3-4 gün) — `tenant_config.gemini_api_key_enc: bytes` (encrypted at rest, AES). /settings'e key set/clear UI. /analyze ve report worker'da tenant key varsa onu kullan, fallback ortak key.
**Bağımlılıklar:** F27 ile birlikte kapanabilir.
**Mevcut mimariye uyum:** Doğal uyum — tenant config zaten JSONB. Encryption layer eklemek gerekiyor (kritik — plaintext key bir tenant'tan diğerine sızarsa felaket). Eski sistemde encryption yoktu (single-user, local file) — yeni mimaride zorunlu.
**Notlar:** Generic özellik. Tenant kendi quotasını yönetmek isteyebilir.

---

### Kart F27 — API key rotation across multiple keys

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:17-55`, `:243-269`
**Ne yapıyor:** `gemini_key.txt` her satırı ayrı bir API key. Quota error (`429`, `Quota`, `403`) yakalanırsa `rotate_api_key()` bir sonraki key'e geçer (round-robin). 10 retry'ya kadar dener.
**Mevcut sistemde durumu:** **YOK** — tek key, quota hatasında 500 dönüyor.
**Karmaşıklık:** Küçük-orta (2 gün) — `imga-core/llm/gemini_provider.py` (varsa) içine rotation logic. Ortak key için config: virgülle ayrılmış IMGA_GEMINI_API_KEYS env, in-memory rotating index. Tenant key için (F26) tek key olduğu için rotation gereksiz.
**Bağımlılıklar:** F26 ile aynı UI'da konumlanabilir.
**Mevcut mimariye uyum:** Doğal uyum — provider seviyesinde transparent.
**Notlar:** Sprint 8.3.X'te bu işe yaramaya başlayacak çünkü Gemini batch traffic Sprint 8.3 sonrası artacak.

---

### Kart F28 — KPI cards (Pos/Neu/Neg %) with click-to-filter

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:1287-1330`
**Ne yapıyor:** Header'ın hemen altında 3 büyük renkli kart (Mavi=Nötr, Yeşil=Pozitif, Kırmızı=Negatif). Her kartın altında "🔍 Filter X" butonu — basıldığında sidebar sentiment filter'ını set eder ve aşağıdaki tüm chart/table o sentiment'a filtrelenir.
**Mevcut sistemde durumu:** **VAR (kısmen)** — `/insights` sayfasındaki SentimentTab'da Pie chart var ama "tıkla → filtre" yok. Dashboard'da 4 metric card var ama farklı KPI'lar (ticket-derived).
**Karmaşıklık:** Küçük (1 gün) — /insights üst tarafına 3 colored card row, click → URL state setParam("sentiment_labels", value).
**Bağımlılıklar:** Yok.
**Mevcut mimariye uyum:** Doğal uyum — URL state pattern Sprint 8.3.3'te kuruldu.

---

### Kart F29 — NPS Score metric

**Hangi sistemde:** cx
**Nerede:** `cx/app.py:1342-1352`
**Ne yapıyor:** F3'le çıkarılan NPS segment dağılımından `((promoters - detractors) / total) * 100` skoru hesaplar, büyük metric olarak gösterir. Yanında pivot tablo (Segment / Count / %).
**Mevcut sistemde durumu:** **YOK** (F3 olmadığı için).
**Karmaşıklık:** F3'e bağımlı; F3 yapılırsa bu trivial.
**Bağımlılıklar:** F3.

---

### Kart F30 — Monthly NPS Trend line chart

**Hangi sistemde:** cx
**Nerede:** `cx/app.py:1605-1659`
**Ne yapıyor:** F2 (date column) + F3 (NPS) ikisi de varsa: tarihleri YYYY-MM gruplandır, her ay için Promoter%, Detractor%, Passive%, NPS Score hesapla, Plotly line chart (markers + text labels) + altında detailed table.
**Mevcut sistemde durumu:** **YOK**
**Karmaşıklık:** Küçük (F2+F3 yapıldıktan sonra ½ gün) — analytics endpoint `GET /tenants/me/analytics/nps-monthly`.
**Bağımlılıklar:** F2 + F3 + F29.

---

### Kart F31 — Experience breakdown cards (Dijital/Operasyonel %) with click-to-filter

**Hangi sistemde:** cx
**Nerede:** `cx/app.py:1356-1392`
**Ne yapıyor:** F9 sınıflandırması varsa: 2 büyük renkli kart (Mavi Dijital, Turuncu Operasyonel). Click → `active_filter` state, tüm aşağı içerik filtrelenir.
**Mevcut sistemde durumu:** **YOK** (F9 olmadığı için).
**Karmaşıklık:** F9 yapılırsa bu trivial.
**Bağımlılıklar:** F9.

---

### Kart F32 — Operational sub-category cards with click-to-filter

**Hangi sistemde:** cx
**Nerede:** `cx/app.py:1444-1513`
**Ne yapıyor:** "📦 Operasyonel Deneyim Detayları" expander içinde 4 küçük renkli kart (Kargo / Depo / Mağaza / Çağrı). Her birinin click filter butonu.
**Bağımlılıklar:** F10.

---

### Kart F33 — Digital sub-category cards with click-to-filter

**Hangi sistemde:** cx
**Nerede:** `cx/app.py:1395-1441`
**Ne yapıyor:** "💻 Dijital Deneyim Detayları" expander, 2 kart (Teknik Arıza / Eksik Özellik), click filter.
**Bağımlılıklar:** F11.

---

### Kart F34 — Stacked bar chart category × sentiment with click-to-filter

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:1515-1593`
**Ne yapıyor:** "Sentiment Analysis by Category" — Plotly stacked horizontal bar (her satır bir kategori, her bar Negatif%/Nötr%/Pozitif% renkli). Negatif % azalan sıralanır. Click event → kategori + sentiment filter, info banner: "🔎 Filtering for: Category=X, Sentiment=Y". "❌ Clear Filter" butonu.
**Mevcut sistemde durumu:** **VAR (kısmen)** — /insights heatmap aynı bilgiyi farklı görselle veriyor (matrix). Heatmap click /reviews'a yönlendiriyor; bar chart inline filter yapıyor — UX farklı.
**Karmaşıklık:** Küçük (1 gün) — /insights'a heatmap'e ek olarak yatay stacked bar chart. Click → URL state setParam.
**Bağımlılıklar:** Yok.
**Mevcut mimariye uyum:** Doğal uyum — Recharts'ta StackedBarChart var.
**Notlar:** Heatmap tek hücreyi vurgulamak için iyi (3 sentiment × N kategori); stacked bar her kategorinin negatif % oranını ranking'iyle gösteriyor — farklı insight. İkisi birlikte yararlı.

---

### Kart F35 — data_editor with row-level "Fix This" + "AI Analiz Et" checkboxes

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:1107-1115`
**Ne yapıyor:** Streamlit `st.data_editor` her satıra iki checkbox kolon: "Select for Correction" (F17 UI loop), "Select for Analysis" (F24 strategic response).
**Mevcut sistemde durumu:** **YOK** — /reviews list pasif, satır click → /reviews/[id]'ye yönlendirir; bulk selection yok.
**Karmaşıklık:** Orta (3-5 gün) — /reviews list'e checkbox kolon, "Toplu İşlem" toolbar ("Düzelt", "Yanıt Taslağı Üret"). Backend: bulk endpoint'ler (F17 ve F24'ün batch versiyonları).
**Bağımlılıklar:** F17 + F24 ile birlikte daha anlamlı.
**Mevcut mimariye uyum:** Doğal uyum.

---

### Kart F36 — Sentiment filter sidebar selectbox

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:312`
**Ne yapıyor:** Sidebar'da "Show Sentiment: All / Pozitif / Nötr / Negatif" dropdown. data_editor'ı filtreler.
**Mevcut sistemde durumu:** **VAR (eşdeğer)** — /reviews ve /insights filter bar'ında sentiment_labels CSV var. Tek dropdown vs CSV multi-select fark.
**Notlar:** Eski sistem tek seçim; yeni sistem multi-select. Yeni daha esnek; karta gerek yok aslında — "TAMAMLANMIŞ" sayılır.

---

### Kart F37 — Cache & Reset button

**Hangi sistemde:** cx (DEDAS'ta yok)
**Nerede:** `cx/app.py:328-331`
**Ne yapıyor:** Sidebar'da "🧹 Clear Cache & Reset" butonu — tüm `st.session_state` temizler, st.cache_data.clear(), rerun.
**Mevcut sistemde durumu:** N/A — yeni mimari Streamlit cache kullanmıyor; TanStack Query var. /reviews'da "yenile" butonu zaten var.
**Karmaşıklık:** -
**Notlar:** Eski sisteme özgü, yeni mimaride karşılığı yok / gereksiz. **Önerim: SKIP**.

---

### Kart F38 — Performance options (max rows slider 100-10000)

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/app.py:334-335`
**Ne yapıyor:** Sidebar expander "⚡ Performance Options" altında "Max Rows to Process" slider. cx default 5000, DEDAS default 1000.
**Mevcut sistemde durumu:** N/A — batch upload'ta 50K cap zaten var, kullanıcı dosyayı kendisi sınırlıyor.
**Notlar:** **SKIP** — eski sisteme özgü Streamlit-friendly tasarım.

---

### Kart F39 — Auto-process on file upload (no button)

**Hangi sistemde:** cx (DEDAS'ta button var)
**Nerede:** `cx/app.py:1747-1759`
**Ne yapıyor:** Yeni dosya upload edilir edilmez `process_dataframe` çağrılır, kullanıcının "Analiz Et" butonuna basmasına gerek yok.
**Mevcut sistemde durumu:** **YOK** — /analyze/upload'ta kullanıcı dosyayı seçer, sonra "Yükle ve Analiz Et" butonu basar.
**Karmaşıklık:** Çok küçük — sadece UX değişikliği.
**Notlar:** Çelişkili UX kararı — confirm before async job pattern güvenli (yanlış dosya yükleme önlenir). **Önerim: SKIP** ya da config flag ile.

---

### Kart F40 — Custom CSS branding (logo, tab styles, KPI color cards)

**Hangi sistemde:** cx (DEDAS'ta tek logo)
**Nerede:** `cx/app.py:66-102`, `:276-286`
**Ne yapıyor:**
- Sidebar'da yan yana 2 logo (varsa local `logo.png`, yoksa Ebebek SVG fallback)
- Custom CSS: `.block-container` padding, h1-h3 Segoe UI 600 weight, `.stMetric` border + shadow, Tab styling (rounded #ff4b4b active red bg)
- KPI cards inline HTML+CSS (gradient renkler)

**Mevcut sistemde durumu:** **VAR (eşdeğer)** — Tailwind 4 + shadcn-on-base-ui ile zaten tutarlı bir tasarım sistemi var. Tenant logosu (F26 ile birlikte) eksik.
**Karmaşıklık:** Küçük (2 gün) — TenantConfig'e `logo_url: str | None`, AppShell'in sidebar header'ında render. Tema renkleri (--chart-1..5) zaten tenant-agnostic.
**Bağımlılıklar:** Yok.
**Notlar:** Generic özellik — her tenant kendi logosunu görür. Mevcut tasarımdan bozmadan eklenebilir.

---

### Kart F41 — Debug info expander

**Hangi sistemde:** cx
**Nerede:** `cx/app.py:337-343`
**Ne yapıyor:** Sidebar'da expander, processed_df'in kolonlarını ve 'Analyzed_Date' var/yok kontrolünü gösterir.
**Mevcut sistemde durumu:** N/A — production'da Sentry/CloudWatch + dev'de browser DevTools/Network panel kullanılıyor. Streamlit-spesifik debug expander generic dashboard'a uymuyor.
**Notlar:** **SKIP**.

---

### Kart F42 — SWOT prompt persona variants (Yunus Emre vs Senior CX Strategist)

**Hangi sistemde:** Her ikisi (farklı persona)
**Nerede:**
- `cx/app.py:391-414` — "Kıdemli CX Stratejisti" persona
- `dedas/app.py:349-372` — "Filozof Stratejist & Ozan (Yunus Emre Ruhu)" persona

**Ne yapıyor:** SWOT prompt'unun ton/üslup ayarı.
**Mevcut sistemde durumu:** N/A (SWOT yoksa persona da yok — F22'ye bağlı).
**Notlar:** F22 yapılırsa: Tenant config'te `swot_persona_style: 'professional' | 'poetic'` (default professional). 2-3 preset prompt persona'sı kayıtlı, kullanıcı seçebilir. Generic — her tenant rapor üslubunu seçer.

---

### Kart F43 — CSV migration helper (`migrate_csv.py`)

**Hangi sistemde:** Her ikisi
**Nerede:** `cx/migrate_csv.py` (24 satır)
**Ne yapıyor:** Eski format `training_data.csv`'yi yeni format'a dönüştürür (quoting fix, missing column handling). Tek seferlik dev tool.
**Mevcut sistemde durumu:** N/A
**Notlar:** **SKIP** — eski sistemden veri taşıyacaksak F17 yapıldığı sırada ad-hoc script.

---

### Kart F44 — `cx_params.json` (SLA rules — F18'in storage tarafı)

**Bağlam:** F18 ile birlikte; ayrı bir özellik kart değil, F18'in persistans bileşeni.

---

### Kart F45 — Auto-detect new file change (cache invalidation)

**Hangi sistemde:** cx
**Nerede:** `cx/app.py:295-300`
**Ne yapıyor:** Eğer yeni file upload edilirse `st.session_state['last_uploaded_file']` ile karşılaştırır, farklıysa `processed_df` ve `exec_brief` cache'lerini temizler.
**Mevcut sistemde durumu:** N/A — yeni mimaride her batch upload yeni `batch_job_id`, otomatik ayrı.
**Notlar:** **SKIP** — Streamlit'e özgü.

---

## 4. Code samples (önemli özellikler için)

### F8 — 23-cat Şirket Perspektifi (excerpt)
```python
def get_company_perspective(text):
    if not isinstance(text, str): return "-"
    t = text.lower()

    # 23 if-elif chain — sample first 4
    if any(kw in t for kw in ["kargom nerede", "gelmedi", "teslim edilmedi", "ulaşmadı", "gecikti"]):
        return "Kargom ulaşmadı"
    if any(kw in t for kw in ["kırık", "deforme", "ezik", "hasarlı", "parçalanmış", "yırtık ürün", "defolu"]):
        return "Deforme-Kırık Ürün"
    if any(kw in t for kw in ["paket", "özensiz", "yırtık paket", "kutu ezik", "ambalaj"]):
        return "Özensiz Paketleme"
    if any(kw in t for kw in ["yanlış ürün", "farklı ürün", "eksik ürün", "sipariş ettiğimden farklı"]):
        return "Yanlış-Eksik Ürün"
    # ... 19 daha
    return "Genel ve Diğer Sorunlar"  # fallback
```

### F18 — DEDAS variant: SLA hour/minute extraction
```python
day_match = re.search(r'(\d+)\s*(?:gün|iş günü|hafta)', orig_text)
detected_val = 0
unit_found = ""

if day_match:
    detected_val = int(day_match.group(1))
    if "hafta" in day_match.group(0): detected_val *= 7
    unit_found = "Gün"

if not unit_found:
    hour_match = re.search(r'(\d+)\s*saat', orig_text)
    if hour_match:
        detected_val = int(hour_match.group(1))
        unit_found = "Saat"
    else:
        min_match = re.search(r'(\d+)\s*dakika', orig_text)
        if min_match:
            detected_val = int(min_match.group(1))
            unit_found = "Dakika"

if unit_found:
    for rule in params.get("sla_rules", []):
        if any(kw in orig_text for kw in rule["keywords"]):
            if rule.get("unit", "Gün") == unit_found:
                if detected_val <= rule["limit"]:
                    score = 0.05; label = "Pozitif"
                else:
                    score = -0.60; label = "Negatif"
            break
```

### F22 — SWOT prompt with stats injection
```python
extra_context = ""
if stats_summary:
    extra_context = f"\n    Kritik Metrikler (Doğrulanmış Veri):\n    {stats_summary}\n"

prompt = f"""
Rol: Kıdemli Müşteri Deneyimi (CX) Stratejisti
...
4. Analiz Yapısı:
   - **Güçlü Yönler:** ...
   - **STRATEJİK TAVSİYE:** Üst yönetim için somut, ölçülebilir öneriler.
     *Önemli*: Tavsiyelerini "Kritik Metrikler" verisi ile (yüzdelerle) destekle.
     Hayali rakam uydurma.
     Örn: "Lojistik süreçlerini iyileştirin" deme ->
     "Şikayetlerin %30'unu oluşturan Teslimat Gecikmeleri için X aksiyonunu alın."

{extra_context}

Yorum Verisi: "{safe_text}"
"""
```

### F24 — Strategic Response prompt (Twitter-aware)
```python
prompt = f"""
Sen şikayetin muhatabı olan kurumun 'İmga' isimli kurumsal yapay zeka asistanısın.

ÖNEMLİ: Şikayet doğrudan SENİN temsil ettiğin kuruma yapılmıştır. Asla kurumu
3. şahıs (o, onlar) olarak anma. Kurumu sahiplen ama "Biz" dili kullan.

Müşteri Şikayeti: "{text}"

Görevin:
1. Seviyeyi belirle (1-4). (1: Rutin, 4: Kritik/Viral Riski)
2. Duygu durumunu belirle.
3. Profesyonel, empatik yanıt taslağı yaz. (Maksimum 280 karakter — Twitter sınırı)
4. Strateji belirle ("DM'e yönlendir", "Hemen ara", "Standart prosedür").

Çıktı Formatı (Satır Satır):
SEVİYE: [Seviye]
DUYGU: [Duygu]
YANIT: [Metin] (Maksimum 280 karakter)
STRATEJİ: [Not]
"""
```

### F27 — API key rotation
```python
def rotate_api_key():
    global CURRENT_KEY_INDEX, GEMINI_API_KEY
    if not API_KEYS: return False
    CURRENT_KEY_INDEX = (CURRENT_KEY_INDEX + 1) % len(API_KEYS)
    GEMINI_API_KEY = API_KEYS[CURRENT_KEY_INDEX]
    genai.configure(api_key=GEMINI_API_KEY)
    return True

# In retry loop:
for attempt in range(10):
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        err = str(e)
        if "429" in err or "Quota" in err or "403" in err:
            if rotate_api_key():
                time.sleep(1)
                continue
        # ...
```

---

## 5. İlk gözlemler (kullanıcıya teknik notlar)

1. **F8 (23-cat Şirket Perspektifi) mevcut sistemde sadece DEDAS-style 4-cat olarak var.** Yeni mimari yorumları ben yazdığımda bunu görmedim — perspectives.py'de "intentionally omitted" diyen yorum var ama ihmal edilen aslında F12 (Smart Rules JSON), F8'in yeni 23-cat heuristic'i kayıt değil — onu da almak gerekir.

2. **Yorum Özet (F5) imga'da var ama UI'a yansımamış.** `/reviews` list'te bu kolon yok, `/reviews/[id]`'de de yok. Eski sistemde data_editor'da hızlı tarama için en değerli kolon — yeni UI'a getirmek değer katar.

3. **NPS (F3) en sık talep edilecek özellik** — Türkiye CX endüstrisinde standart metrik. F3+F29+F30 paketi birlikte yapılırsa /insights'a yepyeni bir analitik dimension açar.

4. **F22 SWOT + F23 OKR kombinasyonu — eski sistemin "executive" wow factor'üydü.** Mevcut sistemde executive-summary metric cards var ama narrative analysis yok. SWOT + OKR yapılırsa bir tenant admin'in haftalık raporlama çıktısı: "Bugün analiz et, SWOT al, OKR'leri çek, slide'a yapıştır" akışı kurulur.

5. **F17 KB UI correction loop atlanmış olabilir.** Yeni sistemde KB override module'ü var ama düzeltme arayüzü yok — yani modeli "yanlış" diyebileceğin bir buton yok. Production tenant'lar bunu hızla isteyecek; bu olmadan KB sadece imga developer tarafından enriched.

6. **F18 SLA cx versiyonu DEDAS versiyonundan REGRESS'lenmiş** — cx 1933 satırlık olmasına rağmen cx'in BERT loop'unda SLA hour/minute extract'i YOK. Sanki cx versiyonu yazılırken birisi DEDAS'taki SLA logic'ini sadeleştirmiş. Mevcut imga DEDAS'tan port'lanmış ama hour/minute kısmını da almamış.

7. **F12 Smart Rules JSON runtime extension kritik özellik** — kullanıcı UI'dan runtime'da kategori sözcüğü ekleyebilirse modeli kendi domain'iyle eğitir. Sprint 7.4'te tenant config introduce edildi; bu pattern'in doğal uzantısı.

8. **Eski sistemdeki "click-to-filter" deseni (F28, F32-34) yeni sistemin URL state pattern'iyle 1:1 eşleşiyor** (Sprint 8.3.3'te kuruldu). Bu kartlar uygulanırsa yapım kolay; mimari hazır.

9. **F26 Custom Gemini API Key tenant config + encryption gerektiriyor** — production'da plaintext key ifşası felaket. AES-256 at-rest minimum. Bu özellik "küçük UI" gibi görünür ama securit-y açıdan dikkat.

10. **F40 Custom branding (logo)** generic özellik. Şu an her tenant aynı imga logosunu görüyor. Kolay bir QoL kazanımı.

---

## 6. Önerilen çalışma sırası (bağımlılık grafiği)

Kullanıcı seçim yaptıktan sonra, **bağımlı olanlar birlikte yapılırsa** çıktı daha tutarlı olur.

**Bağımsız (paralel yapılabilir):**
- F1 — auto text-column detect
- F5 (UI) — Yorum Özet'i /reviews list'e taşı
- F8 — 23-cat Şirket Perspektifi
- F14, F15, F16 (parite — zaten var)
- F19 — Tier2 issue check
- F20 — Risk Durumu UI
- F28 — KPI cards click-filter
- F34 — Stacked bar chart click-filter
- F40 — Logo / custom branding

**Önce altyapı, sonra UI:**

```
F2 (date column)
  └─> F30 (monthly trend), F22+F23 (SWOT + OKR)

F3 (NPS column)
  └─> F29 (NPS metric)
  └─> F30 (Monthly NPS trend) — F2 ile birlikte

F4 (source URL)
  └─> F25 (tweet ID extract)
  └─> F24 (Strategic Response) ile entegre

F9 (Experience type)
  └─> F10 (Op subcat), F11 (Dig subcat)
       └─> F31 (Exp breakdown cards), F32 (Op cards), F33 (Dig cards)

F12 (Smart Rules JSON runtime)
  └─> F8'i extends ediyor
  └─> /settings UI

F17 (KB UI correction loop)
  └─> F35 (data_editor row checkboxes) bağlamı

F18 (SLA hour/minute + custom)
  └─> /settings UI (F12 ile aynı yer)

F22 (SWOT)
  └─> F23 (OKR)
  └─> F42 (persona selector)

F26 + F27 (Tenant Gemini key + rotation)
  └─> Encryption layer (yeni)

F24 (Strategic Response)
  └─> F4, F25 ile birlikte tam Twitter integration
  └─> F35 (bulk selection) ile batch generation
```

**Önerilen 3 dalga:**

**Dalga 1 — Altyapı + low-risk UI (Sprint 8.3.5):**
F1, F2, F3, F4, F9, F10, F11, F20 (UI), F40

**Dalga 2 — Heuristic genişlemeleri + analytics (Sprint 8.3.6):**
F8, F12, F18, F19, F28, F29, F30, F31, F32, F33, F34, F36 (eşdeğer), F5 (UI taşı)

**Dalga 3 — AI executive (Sprint 8.3.7):**
F17, F22, F23, F24, F25, F26, F27, F35, F42

Toplam tahmini efor: **~25-35 iş günü** (3 dalga).

---

## 7. SKIP listesi (eski sisteme özgü, taşımaya değmez)

- F37 (Cache & Reset) — Streamlit cache'e özgü
- F38 (Performance options slider) — yeni mimaride 50K cap zaten var
- F39 (Auto-process on upload) — yeni UX'te confirm-then-job pattern güvenli
- F41 (Debug expander) — production'da Sentry/CloudWatch var
- F43 (CSV migration helper) — ad-hoc script, ihtiyaç anında yazılır
- F45 (Auto-detect file change) — yeni mimaride batch_job_id zaten ayrı

---

## Sonuç

**~30 üzerinde "evet, hayır" karar noktası.** Kullanıcı bu kartlardan tek tek seçecek, seçim listesine göre Sprint 8.3.5+ spec'i şekillenecek. **En değerli 3 öneri (sübjektif):** F22+F23 paketi (SWOT+OKR), F3+F29+F30 paketi (NPS), F8 (23-cat). Bu üçü kullanıcıya hemen "wow" verecek özellikler.
