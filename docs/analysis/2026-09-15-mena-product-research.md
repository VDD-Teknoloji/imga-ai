# İmga MENA Analiz ve Ürün Geliştirme Raporu

## Yönetici özeti

İmga'nın Suudi Arabistan ve Dubai açılımında temel ihtiyaç sitenin Arapçaya çevrilmesi değil, farklı dillerdeki müşteri ifadelerinin doğru anlaşılmasıdır. Bu nedenle önerilen mimari, orijinal yorumdan doğrudan duygu ve kategori çıkarır. Çeviri, gerektiğinde insan inceleyiciye yardımcı olan ayrı bir işlem olmalıdır; Türkçe analiz modeline zorunlu giriş kapısı olmamalıdır.

En uygun tek bir Arapça model, İmga'nın gerçek verisiyle karşılaştırmalı ölçüm yapılmadan belirlenemez. Başlangıç değerlendirme listesi: mevcut üretim modeli kontrol grubu; düşük maliyetli Gemini Flash-Lite; daha güçlü güncel Gemini Flash; farklı sağlayıcıdan GPT-5.6 Terra; Arapça odaklı kendi altyapısında çalışma seçeneği için JAIS 2. Bunlar ölçüm adaylarıdır, doğruluğu kanıtlanmış sıralama değildir. Üretimdeki model ve müşteri anahtarları bu geliştirme kapsamında otomatik değiştirilmemiştir.

Ürün üç yeni çalışma alanı ile genişletildi: **Ürün gereksinimleri**, **Şirket ve süreçler**, **Müşteri kayıp riski**. Yaşayan PRD kanıt, kabul ölçütü ve sorumlu üzerinden olgunlaşır. Şirket bilgisi taslak/onay ayrımıyla saklanır ve yalnız onaylı sürüm yönetici analizlerini besler. Churn ilk sürümde açıklanabilir bir öncelik puanıdır; eğitilmiş model, gelecekteki kayıp olasılığı veya nedensel etki tahmini değildir.

Bu raporda model özellikleri ve fiyatlar için esas alınan erişim tarihi 15 Eylül 2026'dır. Sağlayıcı katalogları hızlı değişir; sözleşme ve satın alma öncesinde yeniden doğrulanmalıdır. Gerçek sağlayıcılarda ücretli karşılaştırmalı deney ve ana dili Arapça/Urduca olan uzmanların etiketleme çalışması bu sürümün doğrulanmış çıktıları arasında değildir.

## 1. Ürün problemi ve mevcut kodun sınırları

### 1.1 Çeviri ile analiz birbirinden ayrılmalı

Bir Arapça yorumun iyi Türkçe çevirisini üretmek, doğru duygu, işletme kategorisi ve alt kategori üretmekle aynı görev değildir. Çeviri sırasında nezaket, ironi, olumsuzluk, yerel kelime anlamı veya zamir referansı değişebilir. Ardından Türkçe anahtar kelime kurallarının uygulanması ikinci bir hata katmanı ekler.

Örneğin, teşekkür ifadesi içeren bir gecikme şikâyeti olumlu kabul edilmemeli; bir siparişin iptal edilmesi de müşterinin şirketle ilişkisini sonlandırdığı şeklinde yorumlanmamalıdır. Bu ayrım özellikle churn için önemlidir. Risk puanında kullanılan iptal bilgisi yorumdan otomatik çıkarılmak yerine kaynak sistemde açıkça bildirilen ilişki sonlandırma talebidir.

Arapça lehçe çevirisine ilişkin 2026 tarihli çalışma 16 lehçeyi, çeşitli açık modelleri ve GPT-4.1'i karşılaştırıyor; lehçeler arası farklar ve değerlendirme sınırlılıkları var. Bu çalışma lehçe bazlı testin gerekliliğini destekler, ancak İmga için güncel model şampiyonu veya duygu sınıflandırma doğruluğu vermez. [1: Jon, Bondok ve Bojar, AbjadNLP 2026](https://aclanthology.org/2026.abjadnlp-1.41/)

### 1.2 İncelemede belirlenen teknik boşluklar

| Mevcut yapı | MENA / yeni özellikler açısından sorun | Uygulanan yaklaşım |
|---|---|---|
| Türkçe BERT ve Türkçe override katmanları | Arapça/Urduca için geçerli oldukları gösterilmemiş | MENA birleşik analizinde Türkçe ön/son kurallar kullanılmıyor |
| Birleşik promptta 600 karakterlik kısaltma | Uzun yorumun sonundaki olumsuzluk veya asıl sorun kaybolabilir | MENA girdisi korunuyor; 6.000 karakter üstü sessiz kesilmek yerine reddediliyor |
| LLM yanıtlarında eksik satırı nötryle tamamlama | Sağlayıcı hatası gerçek nötr görüş gibi görünebilir | MENA için indeks, adet, etiket, sayı ve dil sözleşmesi katı doğrulanıyor |
| Parçalar arasında çoğalan model eşzamanlılığı | İç içe paralellik kota ve bellek baskısı oluşturabilir | İşin ortak MENA motorunda en fazla üç çağrı; alt çağrı en fazla 10 yorum |
| LLM başarısızlığında klasik modele dönüş | Yabancı dilde sessiz kalite kaybı | Manuel ve toplu MENA yolunda Türkçe BERT'e dönüş engelleniyor |
| Review üzerinde kalıcı CRM kimliği olmaması | Tek müşteri geçmişi kurulamaz | İsteğe bağlı kanonik müşteri kimliği ekleniyor |
| Kısa şirket açıklaması | Süreç sahibi, devir, hedef ve kaynak bilgisini ifade edemez | Sürümlü organizasyon ve süreç kataloğu |
| Sabit olmayan ihtiyaç dokümanı | Karar, kanıt ve eksik bilgi izlenemez | Soru odaklı, onaylı/sürümlü PRD |
| Yalnız yorumlardan churn çıkarma beklentisi | Memnuniyetsizlik, kayıp olasılığına eşit değil | CRM gözlemleri + bağlı yorum sinyalleri, eksik veri durumuyla puanlama |

Bu tablo tüm eski performans sorunlarının çözüldüğü anlamına gelmez. Önceki 2.852 satırlık üretim takılması için süreç yığını, sağlayıcı beklemeleri ve bellek profili hâlâ ayrı saha kanıtı gerektirir. Bu geliştirmedeki 3.000 satır testi sağlayıcı taklidi kullanır; gerçek kota, ücret, ağ gecikmesi ve yerel dil başarımını ölçmez.

## 2. Dil kapsamı

İlk pazarlarda tek bir “Arapça” test kümesi yeterli değildir. Önerilen kapsam aşağıdaki dil dilimlerini ayrı ölçer:

| Dil / biçim | İlk pazarla ilişkisi | Testte aranacak özellik |
|---|---|---|
| Modern Standart Arapça | Resmî iletişim ve yazılı destek | Net şikâyet, talep, gerekçe ve olumsuzluk |
| Suudi Arapçası | Suudi Arabistan | Necd, Hicaz ve bölgesel kullanım farkları |
| Körfez / Emirlik Arapçası | Dubai ve BAE | Yerel destek, teslimat, iade ve ücret ifadeleri |
| Urduca, Urdu yazısı | Hedef pazarlardaki Urduca konuşan müşteriler | Arapçayla karıştırılmayan dil analizi |
| Roman Urdu | Latin harfleriyle Urduca | Yazım varyantları ve İngilizceyle karışık cümleler |
| Arabizi | Latin harfleri ve rakamlarla Arapça | Yazım varyantı, lehçe, harf/rakam karışımı |
| İngilizce + Arapça/Urduca | Çok dilli müşteri iletişimi | Aynı yorumda dil değişimi |
| Türkçe | Mevcut müşteriler | Regresyon olmaması |

Unicode Arap yazısı tespiti **dil tespiti değildir**: Urduca ve başka diller de bu yazıyı kullanır. Uygulamadaki yazı kontrolü yalnız yanlışlıkla Türkçe kurallara düşmeyi önleyen korumadır. Satırın dil etiketi modelden gelir; belirsiz veya kapsam dışı dil insan incelemesine bırakılır. Roman Urdu ve Arabizi Latin karakterli olduğu için kurumun MENA profilini açması gerekir.

Roman Urdu için paralel metin kaynağı olan ERUP gibi araştırmalar yardımcı olabilir; ancak çeviri veri kümesi doğrudan müşteri deneyimi sınıflandırmasının etiketli doğrulama kümesi değildir. Lisans ve hedef alan uygunluğu ayrıca değerlendirilmelidir. [2: ERUP, 2024](https://arxiv.org/abs/2412.17562)

## 3. Model araştırması ve seçim

### 3.1 Aday matrisi

| Aday | Doğrulanmış ürün özelliği | İmga için önerilen rol | Karar sınırı |
|---|---|---|---|
| Mevcut Gemini / OpenRouter modeli | Projede kurum bazlı sağlayıcı seçimi mevcut | Aynı veriyle kontrol grubu | Mevcut kullanım, Arapça başarım kanıtı değildir |
| Gemini 3.1 Flash-Lite / 3.5 Flash-Lite | Resmî katalogda yüksek hacimli metin işleme ve çeviri odaklı modeller | Ekonomik doğrudan sınıflandırma adayı | Lehçe/Urduca duygu doğruluğu yerel ölçüm ister |
| Güncel güçlü Gemini Flash | Mevcut sağlayıcı ailesiyle uyumlu karşılaştırma | Zor örnekler için kalite adayı | Sürüm kodu ve kullanılabilirlik hesapta sabitlenmeli |
| GPT-5.6 Terra | Resmî model karşılaştırmasında yapılandırılmış çıktı desteği | Farklı sağlayıcıdan kontrol / kalite adayı | İmga verisinde üstünlük gösterilmedi; yeni doğrudan adaptör eklenmedi |
| Claude ailesi | Resmî çok dillilik değerlendirmeleri mevcut | Bağımsız karşılaştırma adayı | MMLU puanı çeviri veya müşteri duygu doğruluğu değildir |
| JAIS 2, 8B / 70B | Arapça-İngilizce odaklı açık ağırlıklı modeller | Veri yerleşimi ve kendi altyapısı gereksinimi olan Arapça projeler | Urduca eşdeğer yetkinlik varsayılmamalı; GPU/işletim maliyeti ayrı |
| Google Translation LLM | Arapça, ar-SA ve Urduca resmî dil listesinde | İsteğe bağlı insan inceleme çevirisi / deney kontrolü | Doğrudan kategori/duygu motorunun yerine konmamalı |
| Azure Translator | Arapça ve Urduca dil desteği | Kurumsal çeviri karşılaştırması | Özelliklerin bölge/model bazında kapsamı kontrol edilmeli |
| TranslateGemma | Google model kartında 4B/12B/27B ve 55 dil | Yerel çeviri deneyi | 2K bağlam ve özel istem biçimi; sınıflandırma modeli değil |
| NLLB-200 distilled 600M | Model kartında CC-BY-NC lisans | Akademik/offline araştırma için lisans değerlendirmesi | Ticari SaaS'ta varsayılan çözüm olarak seçilmemeli |
| DeepL | Dil desteği ayrı resmî sayfa/API üzerinden yayımlanıyor | Gerekirse ek çeviri adayı | Bu incelemede Urduca özelliği ve kısıtları yeterince doğrulanamadı |

Gemini adaylarının ürün konumlandırması ve güncel kodları resmî katalogdan; ücret bilgileri ayrı fiyat sayfasından alınmıştır. [3: Gemini model kataloğu](https://ai.google.dev/gemini-api/docs/models), [4: Gemini fiyatlandırma](https://ai.google.dev/gemini-api/docs/pricing)

OpenAI adayının özellikleri resmî karşılaştırma sayfasına dayanır. Anthropic'in dil tablosundaki göreli başarıyı “Arapça çeviri yüzde doğruluğu” diye okumak hatalıdır; farklı görevler için ayrı ölçüm gerekir. [5: OpenAI model karşılaştırması](https://developers.openai.com/api/docs/models/compare), [6: Claude çok dilli destek](https://platform.claude.com/docs/en/build-with-claude/multilingual-support)

JAIS 2'nin Arapça-İngilizce odağı, bölgesel kullanım açısından anlamlıdır; kendi altyapısında çalışma önerisi bu özelliğe dayanan bir mühendislik değerlendirmesidir, otomatik kalite üstünlüğü iddiası değildir. [7: JAIS 2 resmî duyuru](https://mbzuai.ac.ae/news/inception-cerebras-and-mbzuai-release-jais-2-the-next-generation-of-the-worlds-leading-arabic-open-weight-llm/), [8: JAIS 2 model kartı](https://huggingface.co/inception42/Jais-2-8B-Chat)

Çeviri ürünleri için dil desteği ayrı doğrulanmalıdır. “Arapça destekliyor” demek, bütün Suudi/Emirlik lehçeleri ve Roman Urdu için eşit kalite demek değildir. [9: Cloud Translation dilleri](https://docs.cloud.google.com/translate/docs/languages), [10: Azure Translator dilleri](https://learn.microsoft.com/en-us/azure/ai-services/translator/language-support)

TranslateGemma için Gemma kullanım şartları, NLLB için ticari olmayan kullanım kısıtı değerlendirmeye alınmalıdır. Bir modelin indirilebilir olması, sınırsız ticari kullanım izni anlamına gelmez. DeepL hakkındaki belirsizlik “Urduca desteklemiyor” şeklinde kesin hükme çevrilmemiştir. [11: TranslateGemma model kartı](https://huggingface.co/google/translategemma-27b-it), [12: NLLB model kartı](https://huggingface.co/facebook/nllb-200-distilled-600M), [13: DeepL desteklenen diller](https://developers.deepl.com/docs/getting-started/supported-languages)

### 3.2 Fiyat karşılaştırmasının doğru kurulması

15 Eylül 2026 resmî standart metin tarifesinde Gemini 3.1 Flash-Lite giriş/çıkış fiyatı bir milyon token için 0,25 / 1,50 ABD doları; Gemini 3.5 Flash-Lite için 0,30 / 2,50 ABD dolarıdır. Ayrı sağlayıcı Batch API tarifesi daha düşük olabilir; uygulamanın yorumları paketleyerek normal API'ye göndermesi, sağlayıcının indirimli Batch API'sini kullandığı anlamına gelmez. [4: Gemini fiyatlandırma](https://ai.google.dev/gemini-api/docs/pricing)

OpenAI karşılaştırmasında GPT-5.6 Terra için standart giriş/çıkış fiyatı bir milyon token başına 2 / 12 ABD doları olarak gösteriliyor. Bu fiyat farkı doğrudan aynı görevde kalite farkını ölçmez; deneyde toplam maliyet ve kabul edilebilir yanlış karar sayısı birlikte ele alınmalıdır. [5: OpenAI model karşılaştırması](https://developers.openai.com/api/docs/models/compare)

Karakter bazlı çeviri tarifesi ile token bazlı analiz tarifesini aynı birimmiş gibi karşılaştırmamak gerekir. Google Translation LLM metin çevirisi giriş ve çıkışı ayrı karakter miktarı üzerinden ücretlendirir. [14: Cloud Translation fiyatlandırma](https://cloud.google.com/products/translate/pricing)

İmga maliyet hesabı:

`toplam = giriş_token / 1e6 × giriş_fiyatı + çıkış_token / 1e6 × çıkış_fiyatı + tekrarlar + embedding + varsa çeviri`

Vergi, aracı sağlayıcı, saklama ve sunucu giderleri ayrıca eklenmelidir. Arapça/Urduca için karakterden token'a sabit dönüşüm katsayısı kullanılmamalı; gerçek sağlayıcı kullanım metadatası ölçülmelidir. Prompt, kategori listesi ve düzeltme örnekleri her çağrıda maliyete katılır.

### 3.3 Önerilen karar sırası

1. Üretimdeki sağlayıcı/model kombinasyonunu kontrol grubu olarak sabitle.
2. Flash-Lite adayını aynı şema ve aynı etiketli veriyle test et.
3. Yanlış negatif veya lehçe başarısızlığı yüksekse güçlü Flash ve bağımsız sağlayıcıyla karşılaştır.
4. Doğruluk kabul kapısını geçmeyen ucuz modeli üretime alma.
5. İki sağlayıcı arasında yedekleme yapılacaksa her iki modelin de dil dilimlerini geçtiğini doğrula.
6. Müşteri sözleşmesi veya veri yerleşimi kendi altyapısını gerektiriyorsa JAIS seçeneğini ayrı maliyet/işletim çalışmasıyla değerlendir.
7. Model sürümü değiştiğinde aynı dondurulmuş test kümesini yeniden çalıştır.

## 4. Kalite değerlendirme planı

### 4.1 Veri ve etiketleme

Başlangıç önerisi, izinleri ve anonimleştirmesi tamamlanmış yaklaşık 1.200-2.000 gerçek yorumdur. Bu bir evrensel örneklem standardı değil, pilot planıdır. Her önemli dil diliminde en az yaklaşık 150 örnek hedeflenmeli; müşteri hacmi düşük dilimler için güven aralığının geniş olacağı açıkça gösterilmelidir.

İki yetkin ana dil değerlendiricisi bağımsız etiketlemeli, uyuşmazlıklar üçüncü değerlendirme veya ortak hakemlikle çözülmelidir. Etiketler: duygu, ana kategori, alt kategori, dil/lehçe, müşteri talebinin türü ve belirsizlik gerekçesi. İptal ifadesinde sipariş, abonelik ve ilişki iptali ayrı değerlendirilmelidir.

Aynı müşterinin benzer metinleri eğitim/prompt örnekleri ile bağımsız test arasında bölünmemelidir. Zaman ve kaynak ayrımı uygulanmalıdır. Sentetik örnekler yazılım regresyonu için yararlıdır, gerçek saha doğruluğunun yerine geçmez.

### 4.2 Metrikler

| Alan | Metrik | Neden |
|---|---|---|
| Duygu | Macro-F1, sınıf bazlı precision/recall | Sınıf dengesizliğinde yalnız accuracy yanıltıcıdır |
| Kritik şikâyet | Olumsuz sınıf recall, tehlikeli yanlış pozitifler | Şikâyeti olumluya çevirmek iş açısından maliyetlidir |
| Kategori | Macro-F1, ana/alt kategori uyuşması | Yanlış ekibe yönlendirmeyi ölçer |
| Dil dilimi | Her dil/lehçede ayrı skor ve örnek sayısı | Büyük İngilizce kümesi Urduca hatalarını gizlememeli |
| Belirsizlik | İnsan incelemeye bırakılan oran ve kalan hata oranı | Her girdiye kesin karar vermeyi ödüllendirmemeli |
| Sözleşme | Eksik/tekrar indeks, geçersiz kod, bozuk JSON | Sessiz satır kaybını engeller |
| İşletim | p50/p95 gecikme, tekrar, tamamlanma oranı | Kullanıcı deneyimi ve worker sağlığı |
| Ekonomi | 1.000 yorum ve bir doğru karar başına maliyet | Salt token fiyatından daha anlamlıdır |

Önerilen başlangıç kabul hedefleri: duygu Macro-F1 en az 0,85, kritik dil dilimlerinde en az 0,80, olumsuz recall en az 0,90; bozuk/eksik model çıktısının başarı gibi kaydedilmesi sıfır. Bunlar ölçülmüş sonuçlar değil, ürün sahibi ve dil uzmanlarıyla onaylanacak pilot hedefleridir. Modelin kendi “confidence” değeri kalibre edilmiş olasılık değildir; değerlendirme verisinde ayrıca sınanmalıdır. [15: scikit-learn olasılık kalibrasyonu](https://scikit-learn.org/stable/modules/calibration.html)

## 5. Yaşayan PRD

### 5.1 “16 madde” standardı

Evrensel ve zorunlu bir 16 maddelik PRD standardı doğrulanmadı. PRD içerikleri şirketin ürün yönetimi yöntemine göre değişir. Atlassian'ın kılavuzu hedefler, varsayımlar, kullanıcı hikâyeleri, tasarım ve kapsam dışını içeren yaşayan bir ortak çalışma belgesi önerir; belirli bir patronun kullandığı 16 adımı kanıtlamaz. [16: Atlassian PRD kılavuzu](https://www.atlassian.com/agile/product-management/requirements)

İmga için aşağıdaki **değiştirilebilir başlangıç şablonu** eklendi. Patronun çerçevesi geldiğinde başlıklar, sorular ve sıra değiştirilebilir; bölüm eklenebilir veya silinebilir. Kimlikler ve önceki sürümler geçmişi korur. Şablon kurumun resmî yöntemiymiş gibi sunulmamalıdır.

| # | Başlık | Olgunlaşması gereken karar |
|---|---|---|
| 1 | Problem ve kanıt | Kimin hangi gerçek sorunu? |
| 2 | Vizyon ve stratejik uyum | Neden bu ürün, neden şimdi? |
| 3 | Kullanıcılar ve karar vericiler | Kullanıcı, satın alan, onaylayan kim? |
| 4 | Pazar, ülke ve dil | Ülke, sektör, dil ve kanal kapsamı |
| 5 | Başarı ölçütleri | Başlangıç, hedef, kaynak ve tarih |
| 6 | Kapsam ve kapsam dışı | İlk sürümün sınırları |
| 7 | Kullanıcı yolculukları | Veriden karara ve takibe adımlar |
| 8 | Fonksiyonel gereksinimler | Rol, davranış, hata durumları |
| 9 | Veri ve entegrasyonlar | CRM kimliği, olay zamanı, izinler |
| 10 | Yapay zeka ve doğrulama | Modeller, etiketli veri, kabul kapıları |
| 11 | Organizasyon ve süreçler | Sorumluluk, devir, SLA ve eskalasyon |
| 12 | Müşteri kaybı ve müdahale | Kayıp tanımı ve müdahale sorumlusu |
| 13 | Gizlilik ve yetkiler | Erişim, işleme yeri, silme |
| 14 | Kalite ve işletim | Hız, maliyet, erişilebilirlik ve hata bütçesi |
| 15 | Yayın ve kabul planı | Pilot, bağımlılıklar ve geri dönüş |
| 16 | Riskler ve açık kararlar | Varsayım, karar sahibi ve son tarih |

### 5.2 Soru ve onay davranışı

Her bölümde yanıt, kanıt/kaynak, kabul ölçütü, sorumlu ve durum bulunur. İmga eksik alanları sırayla sorar: önce kararın cevabı, sonra dayanak, ardından ölçülebilir kabul, son olarak sorumlu ve doğrulama. Mevcut sürümde bu soru seçimi deterministiktir; maliyetli bir LLM çağrısı veya kendiliğinden bilgi üretimi yoktur.

“Doğrulandı” için dört temel alanın dolu olması gerekir. Kapsam dışı seçilen bölüm gerekçe ister. Olgunluk göstergesi kapsam içindeki doğrulanmış bölüm oranıdır, dokümanın gerçek dünyada doğru olduğuna dair yapay zeka notu değildir.

Analist taslak kaydedebilir. Kurum yöneticisi gerekli alanları tamamlanmış PRD'yi yayınlar. Her kayıt yeni sürümdür; aynı sürümü açmış iki kullanıcının yazmaları çakışırsa ikinciye 409 verilir, ilk kullanıcının değişikliği ezilmez. Markdown dışa aktarma ve sürüm geçmişi mevcuttur.

## 6. Şirket ve süreç zekası

### 6.1 Veri modeli

Şirket profili amaç, iş modeli, pazarlar, saat dilimi, kısıtlar, yorum analiz profili ve AI rapor dilini taşır. Organizasyon birimleri benzersiz kimlik, üst birim, hesap veren rol ve görev/yetki bilgisi içerir. Süreçler sorumlu birim, ilgili yorum kategorileri, sıralı adımlar, adım sahipleri, süre hedefi, eskalasyon, kaynak ve doğrulama tarihi taşır.

Döngülü organizasyon ağacı, olmayan üst birim, olmayan süreç sahibi ve gelecekteki doğrulama tarihi reddedilir. Yayın sırasında kategori kodları global ve kuruma özel geçerli kodlarla doğrulanır; taslakta henüz tanımlanmamış kategori planlanabilir. Model bağlamının kontrolsüz büyümemesi için toplam şirket dokümanı UTF-8 biçiminde 64 KiB ile sınırlıdır. Kategori eşlemesi bir operasyonel ilişkilendirmedir; yorumun gerçek süreç örneği veya kök neden kimliği değildir. Tam süreç madenciliği için ayrıca `case_id, activity, started_at, completed_at, actor_role, system` gibi olay verileri gerekir.

### 6.2 Bulgular

İlk sürüm iki farklı bulgu türünü ayırır:

- **Tanım eksikliği:** sahibi olmayan birim/süreç, adım veya hedef eksikliği, kaynak/doğrulama eksikliği, belirsiz kategori eşlemesi.
- **İnceleme sinyali:** yeterli sayıda yorumda olumsuz pay artışı veya süreç hedefi üzerindeki çözüm sürelerinin belirli eşiği aşması.

Olumsuz pay karşılaştırması son 30 gün ve önceki 30 günde en az 20'şer yorum gerektirir; 20 yüzde puan artış başlangıç inceleme eşiğidir. Süreç çözüm hedefi için en az 10 geçerli ölçüm ve en az yüzde 20 aşım gerekir. Bunlar istatistiksel anlamlılık testi, anomali modeli veya nedensellik kanıtı değildir.

Gelecek tarihli, silinmiş ve kalite dışı yorumlar kullanılmaz. Yeni MENA kayıtlarında düşük güvenli veya kapsam dışı/belirsiz dil çıktıları yeni churn/süreç sinyallerine alınmaz. Az veri “sağlıklı şirket” olarak değil, yetersiz veri olarak gösterilir.

### 6.3 Yönetici raporlarına bağlantı

Onaylı şirket bağlamı yönetici özeti, SWOT, OKR ve kök neden istemlerine eklenir. Modelden belgelenmiş süreç ve sorumlu kimliklerini kullanması, kanıtı hipotezden ayırması, kişi performansı veya nedensellik uydurmaması istenir.

Taslak kayıt mevcut yayınlı bağlamı değiştirmez. Yayınlı içerik parmak izi önbellek anahtarlarına katılır; eski bağlamla üretilmiş kök neden çıktısı güncel analizmiş gibi geri verilmez. Tarihsel raporlar tarihsel kayıt olarak korunur.

Süreç tanımları modele referans veri olarak gönderilir, talimat olarak kabul edilmez. Bu koruma tek başına prompt injection riskini ortadan kaldırmaz; belge düzenleme yetkisi, insan onayı ve sınırlı çıktı sözleşmesi birlikte gereklidir.

## 7. Müşteri kayıp riski

### 7.1 Doğru kayıp tanımı

Kayıp tanımı iş modeline bağlıdır: abonelik iptali, yenilememe, belirli süre alışveriş yapmama veya sözleşme sonlandırma birbirinin yerine kullanılamaz. İlk sürüm bu tanımlardan birini LLM'e tahmin ettirmez. CRM'den gelen müşterinin yaşam döngüsü, gözlem tarihi ve açık iptal bilgisi esas alınır.

Müşteri kimliği şirketin kaynak sistemindeki kanonik, kararlı kimliktir. Ad, telefon benzerliği veya metindeki kişi adı üzerinden kimlik eşlemesi yapılmaz. `0001` gibi baştaki sıfırlar CSV'de korunur. Excel kimlik hücresi sayı olarak kaydedildiyse daha önce kaybolan sıfırlar yazılımla güvenilir biçimde geri getirilemez.

### 7.2 Veri girişleri

Müşteri kartı elle girilebilir veya UTF-8 CSV'den yüklenebilir. İlk sürüm müşteri kaydı aktarımı CSV'dir; mevcut yorum yükleme yolunda CSV/XLSX `customer_id` veya `customer_external_id` kolonu üzerinden müşteri bağlantısı taşınır. Müşteri listesi sınırı kurum başına 5.000, CSV sınırı 5 MiB'dır.

Gözlem: kaynak, gözlem tarihi, son aktivite, beklenen aktivite aralığı, iki ardışık 30 günlük sipariş/kullanım dönemi, vadesi geçmiş fatura, ilişki iptal talebi, yenileme tarihi, isteğe bağlı gelir ve para birimi. Takip: sorumlu, sonraki aksiyon, takip tarihi ve sonuç.

Bilinmeyen değer sıfır değildir. Örneğin “fatura bilgisi yok” ile “gecikmiş fatura sıfır” ayrıdır. Karşılaştırmalı sayaçlarda iki dönem birlikte girilmelidir. Gelecekteki gözlem, negatif sayaç veya para birimsiz gelir reddedilir. Eski gözlem yeni gözlemin üzerine yazılamaz. CSV'nin herhangi bir satırı başarısızsa o aktarımın tamamı geri alınır.

### 7.3 Kurallar

| Sinyal | Başlangıç puanı | Koşul |
|---|---:|---|
| Açık ilişki iptal talebi | 60 | Kaynak sistemde açıkça doğru |
| Sipariş/kullanım düşüşü | 25, birleşik en fazla 35 | Önceki yeterli baz döneme göre en az yüzde 50 azalma |
| Aktivitesizlik | 20 | Gözlem tarihinde beklenen aralığın en az iki katı |
| Gecikmiş fatura | 20 | Bildirilen sayı sıfırdan büyük |
| Tekrarlayan olumsuz görüş | 15 | En az 3 olumsuz ve bağlı yorumların en az yarısı |
| SLA ihlalleri | 10 | En az 2 kayıt, yorum alanı için yeterli geçmiş |
| Düşük NPS | 10 | En az 2 detractor yanıtı, yeterli geçmiş |
| Yakın yenileme | 10 | Başka risk varken yenileme 30 gün içinde |

Toplam en fazla 100. Başlangıç aralıkları: 0-19 düşük, 20-39 izle, 40-59 yüksek, 60-100 kritik. En az iki gözlenen sinyal alanı veya açık iptal olmadan sayısal skor verilmez. Gözlem 14 günden eskiyse eski veri olarak işaretlenir. Aktif olmayan müşteriler aktif kayıp riski sıralamasına sokulmaz.

Bunlar doğrulanmış ekonomik katsayılar değil, şeffaf ilk işletim kurallarıdır. Birbirine bağlı davranış sinyalleri iki farklı bağımsız nedenmiş gibi yorumlanmamalıdır. Ödeme gecikmesinin otomatik hizmet kesintisi veya başka olumsuz otomatik kararlara dönüşmesi bu özelliğin kapsamında değildir.

### 7.4 Müdahale ve öğrenme

Müşteri kartında risk nedenleri, kanıtları ve önerilen insan kontrolü görünür. Hesap sorumlusu bir sonraki aksiyonu, tarihini ve sonucu kaydeder. Geçmiş gözlemler aynı kayıt üzerinde sessizce değiştirilmez; yeni sürüm eklenir. Yönetici müşteri kaydını ve gözlem geçmişini silebilir; yorumlar korunur ancak müşteri bağlantısı kaldırılır.

Eğitilmiş churn modeli için sonraki aşamada müşteri-zaman gözlemleri ve gelecekteki gerçek kayıp etiketleri gerekir. Zamana göre ayrılmış doğrulama, veri sızıntısı kontrolü, PR-AUC, lift@K, kapasiteye göre precision/recall ve olasılık kalibrasyonu değerlendirilmelidir. Retained sonucu tek başına müdahalenin kaybı önlediğini kanıtlamaz; karşılaştırma grubu olmadan ek etki ölçülemez. Kalibrasyon için eğitimde kullanılmayan veri gerekir. [15: scikit-learn kalibrasyon rehberi](https://scikit-learn.org/stable/modules/calibration.html)

## 8. Güvenlik ve bölgesel hazırlık

Suudi Arabistan PDPL ve sınır ötesi veri aktarımı düzenlemeleri açısından veri türü, işleme amacı, aktarım temeli, sözleşmeler ve uygun korumalar değerlendirilmeli. “Bütün Suudi verisi istisnasız ülke dışına çıkamaz” şeklinde genel bir kabul yapılmamalı. Sektör ve müşteri gereksinimleri ayrıca ele alınmalıdır. [17: SDAIA resmî mevzuat kaynakları](https://sdaia.gov.sa/en/SDAIA/about/Pages/RegulationsAndPolicies.aspx)

BAE federal kişisel veri koruma düzenlemesi yanında faaliyet alanı ve özel hukuk bölgesi önemlidir. Dubai'de satış yapmak otomatik olarak yalnız tek rejimin uygulanacağı anlamına gelmez. DIFC ve düzenlemeye tabi sektörler için ayrıca hukuk incelemesi yapılmalıdır. [18: BAE resmî veri koruma bilgisi](https://u.ae/en/about-the-uae/digital-uae/data/data-protection-laws)

Üretim öncesi zorunlu iş listesi: veri envanteri, DPA ve alt işleyen listesi, seçilen API'nin veri saklama/eğitim şartları, bölge/endpoint doğrulaması, işleme izinleri, silme talepleri, yedeklerden silme politikası ve saklama süreleri. Bu rapor hukuki uygunluk sertifikası değildir.

Yeni müşteri/PRD/süreç tablolarında tenant RLS ve FORCE RLS kullanılır. Onay yetkisi sunucu tarafında denetlenir. Müşteri adları ve ham satırlar genel denetim loglarına çoğaltılmaz. Yeni alanlar mevcut üretim verisine otomatik doldurulmaz. Kurum anahtarları, model tercihi ve mevcut Türkçe arayüz dili korunur.

Önemli sınır: müşteri silme işlemi tüm platformda kişisel veri silme işlemi değildir. Serbest metin yorumlar, yüklenen dosyalar, eski raporlar ve yedekler ayrıca kurumun silme/saklama politikasına tabidir. Otomatik CRM senkronizasyonu, bütçe bazlı model yönlendirmesi ve ülke bazlı veri yerleşimi dağıtımı bu sürümde kurulmuş sayılmamalıdır.

## 9. Kabul ve yayın planı

1. Yeni migration'ı staging yedeği üzerinde uygula; üç yeni tablonun RLS/FORCE ve izinlerini doğrula.
2. Mevcut Türkçe müşteride aynı testleri çalıştır; yayınlı MENA bağlamı olmayan kurumun davranışı değişmemeli.
3. Suudi/Dubai pilot kurumu oluştur; doğru kategori tanımları ve yerel terim sözlüğünü gir.
4. PRD'nin açık kararlarını ürün sahibiyle doldur; patronun 16 maddelik yöntemi geldiğinde başlangıç şablonuyla eşle.
5. Şirket bağlamını kaynak belgelerle doldur ve kurum yöneticisine onaylat.
6. CRM kimlikli yorum ve müşteri gözlemlerini küçük örnekle yükle; güncellik ve eşleme oranlarını doğrula.
7. İnsan etiketli yerel dil kabul deneyini tamamla; eşik geçmeden “doğruluğu doğrulanmış MENA ürünü” iddiasıyla satış yapma.
8. Gerçek modelle 98, 1.000 ve 3.000 satır stres testlerini yap; süreç yığını, bellek, kota ve maliyeti kaydet.
9. Churn müdahalelerini insan onaylı pilotta izle; sonuçları kaydet, otomatik müşteri yaptırımı uygulama.
10. Ülke/sözleşme/veri aktarımı değerlendirmesini tamamla; kademeli üretim açılışı yap.

Migration otomatik başlangıç adımı değildir. Üretim runbook'undaki owner bağlantısı ve manuel Alembic adımı kullanılmalıdır. Bu çalışma sırasında üretime dağıtım veya üretim müşteri verisi üzerinde migration yapılmamıştır.

## Kaynaklar

Kaynakların erişim tarihi: 15 Eylül 2026. Tarihi belirtilmeyenler yaşayan resmî dokümantasyondur.

1. Jon, Josef; Bondok, Rawan; Bojar, Ondřej. [Arapça lehçe makine çevirisi değerlendirmesi, AbjadNLP 2026](https://aclanthology.org/2026.abjadnlp-1.41/).
2. [ERUP: English-Roman Urdu Parallel Dataset, 2024](https://arxiv.org/abs/2412.17562).
3. Google. [Gemini model kataloğu](https://ai.google.dev/gemini-api/docs/models).
4. Google. [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing).
5. OpenAI. [Models comparison](https://developers.openai.com/api/docs/models/compare).
6. Anthropic. [Multilingual support](https://platform.claude.com/docs/en/build-with-claude/multilingual-support).
7. MBZUAI. [JAIS 2 resmî duyurusu](https://mbzuai.ac.ae/news/inception-cerebras-and-mbzuai-release-jais-2-the-next-generation-of-the-worlds-leading-arabic-open-weight-llm/).
8. Inception. [JAIS 2 8B Chat model kartı](https://huggingface.co/inception42/Jais-2-8B-Chat).
9. Google Cloud. [Supported languages](https://docs.cloud.google.com/translate/docs/languages).
10. Microsoft. [Translator language support](https://learn.microsoft.com/en-us/azure/ai-services/translator/language-support).
11. Google. [TranslateGemma model kartı](https://huggingface.co/google/translategemma-27b-it).
12. Meta. [NLLB-200 distilled 600M model kartı](https://huggingface.co/facebook/nllb-200-distilled-600M).
13. DeepL. [Languages supported](https://developers.deepl.com/docs/getting-started/supported-languages).
14. Google Cloud. [Translation pricing](https://cloud.google.com/products/translate/pricing).
15. scikit-learn. [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html).
16. Atlassian. [Product requirements document](https://www.atlassian.com/agile/product-management/requirements).
17. SDAIA. [Regulations and policies](https://sdaia.gov.sa/en/SDAIA/about/Pages/RegulationsAndPolicies.aspx).
18. UAE Government. [Data protection laws](https://u.ae/en/about-the-uae/digital-uae/data/data-protection-laws).
