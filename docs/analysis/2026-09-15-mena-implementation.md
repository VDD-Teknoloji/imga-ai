# İmga MENA ve Şirket Zekası: Uygulama ve Doğrulama

Tarih: 15 Eylül 2026. Kapsam: Suudi Arabistan ve Dubai müşterilerinin Arapça/Urduca yorumlarını analiz etmek; yaşayan PRD, şirket/süreç bağlamı ve müşteri kayıp riski çalışma alanlarını ürüne eklemek. Arayüzün Arapça/Urduca çevirisi bu talebin kapsamında değildir.

## 1. Teslim durumu

| Alan | Uygulanan | Henüz doğrulanmamış / sonraki aşama |
|---|---|---|
| MENA analizi | Orijinal dilde birleşik duygu/kategori analizi, dil etiketi, katı çıktı doğrulama, Türkçe fallback koruması | Gerçek sağlayıcılarda ana dil uzmanlarıyla doğruluk karşılaştırması |
| PRD | 16 düzenlenebilir başlangıç bölümü, eksik alan soruları, olgunluk, onay, geçmiş, Markdown indirme | Patronun kendi 16 adımının içerik olarak girilmesi; serbest biçimli LLM mülakatı |
| Şirket/süreçler | Organizasyon ağacı, süreç/adım/sorumlu/hedef/kaynak, yayınlı bağlam, bulgular | Olay kayıtlarıyla süreç madenciliği, nedensel analiz |
| Churn | CRM kimliği, müşteri gözlemleri, CSV aktarımı, açıklanabilir öncelik puanı, takip ve geçmiş | Etiketli müşteri geçmişiyle eğitilmiş ve kalibre edilmiş kayıp olasılığı modeli |
| Güvenlik | Sunucu yetkileri, tenant RLS/FORCE, sürüm çakışması, sınırlı aktarım, denetim kaydı | Bölgesel hukuk/sözleşme onayı, tüm platform için saklama/silme otomasyonu |
| İşletim | İzole PostgreSQL üzerinde migration, gerçek API ile tarayıcı testleri | Üretim dağıtımı, gerçek 3.000 yorum sağlayıcı yük testi |

Bu sürüm kullanılabilir bir ilk ürün uygulamasıdır. “Arapça/Urduca doğruluğu kanıtlandı” veya “churn olasılığı tahmin ediliyor” iddiaları için yeterli saha kanıtı yoktur.

## 2. Ekranlar ve iş akışları

### Ürün gereksinimleri: `/prd`

Başlık ve soru düzenleme, bölüm ekleme/silme/sıralama, yanıt, kanıt/kaynak, kabul ölçütü, sorumlu ve durum alanları bulunur. Sorular son kaydedilen belgeye göre bir sonraki eksik alana ilerler; cevap veya kanıt uydurulmaz. Bir bölümün doğrulanmış içeriği düzenlenince yeniden taslağa döner.

Kapsam dışı bölüm gerekçe ister. Kapsam içindeki bütün bölümler doğrulanmadan yayın yapılamaz. Her kayıt yeni sürümdür; aynı sürüm üzerinden çakışan yazma 409 ile durdurulur. Taslakta kaydedilmemiş değişiklik göstergesi ve sayfadan çıkış uyarısı bulunur. Arşivde eski sürümler ve Markdown indirme vardır.

16 bölüm bir endüstri standardı olarak sunulmaz. Araştırma raporundaki öneri şablonudur; 1-64 bölüm desteklenir.

### Şirket ve süreçler: `/company`

Genel, Organizasyon, Süreçler, Bulgular ve Sürüm geçmişi sekmeleri vardır. Kurumun MENA analiz profili ve AI rapor dili burada seçilir. Bu seçim arayüz dilini değiştirmez.

Organizasyon için üst birim ve hesap veren rol; süreç için sahip birim, kategori kodları, adımlar, adım sahipleri, hedef süre, eskalasyon, kaynak ve doğrulama tarihi girilir. Döngü, olmayan birim ve gelecekteki doğrulama reddedilir. Yayında kategori kodları global ve kuruma özel mevcut kategorilerle denetlenir. Şirket dokümanı toplam 64 KiB UTF-8 ile sınırlıdır.

Taslak, son onaylı şirket bağlamını değiştirmez. Yalnız yönetici yayınlayabilir. Son onaylı bağlam yönetici özeti, SWOT, OKR ve kök neden istemlerine eklenir. Mevcut önbellekli akışlarda içerik parmak izi eski bağlamın güncel sonuç gibi kullanılmasını engeller. Eski tarihsel kayıtlar silinmez.

Bulgular tanım eksikliğini ve operasyonel inceleme sinyalini ayırır. Son 30 gün/önceki 30 gün yorumları ve mevcut çözüm süresi ölçümleri kullanılır. Yetersiz veri açık gösterilir; bu ekran eğitimli bir anomali veya çalışan performans modeli değildir.

### Müşteri kayıp riski: `/churn`

Arama, risk filtresi ve sayfalama; risk dağılımı; müşteri kartı; CSV şablon indirme ve içe aktarma; risk kanıtları; sorumlu, takip tarihi, sonraki aksiyon ve sonuç alanları vardır. Müşteri geçmişi sürümlüdür. Kurum yöneticisi müşteri ve gözlem geçmişini silebilir; ilgili yorumlar korunur, müşteri bağlantıları kaldırılır.

Müşteri verisi elle veya UTF-8 CSV ile girilir. İlk sürümde müşteri hesabı aktarımı XLSX değildir; yorum yükleme tarafındaki mevcut CSV/XLSX yolu korunmuştur. Kurum başına 5.000 müşteri, dosya başına 5 MiB sınırı vardır. Hatalı, yinelenen veya eski tarihli gözlem içeren aktarım tamamen reddedilir; kısmi başarı yoktur. 3.000 satırlık aktarım için mevcut kayıtlar topluca okunur, hesap ve geçmiş kayıtları 500 satırlık veritabanı paketleriyle tek transaction içinde yazılır.

Skor `rules-v1` yöntemidir; 0-100 öncelik puanı, yüzde olasılık değildir. Yetersiz, eski ve aktif olmayan veri için ayrı durumlar vardır. Bilinmeyen finansal/aktivite verisi sıfıra çevrilmez. Açık ilişki iptal talebi yorumdan çıkarılmaz, CRM gözleminden gelir.

Formlarda Arapça/Urduca metin için otomatik metin yönü kullanılır. Yeni ekranların arayüz metinleri mevcut Türkçe/İngilizce sözlüklere bağlanmıştır. Sekme, filtre ve sayfalama URL durumuna bağlıdır; geri/ileri ve yenileme davranışı korunur.

### Yetkiler

| İşlem | Viewer | Analyst | Tenant admin |
|---|---:|---:|---:|
| Belgeleri, bulguları, müşterileri ve geçmişi görüntüleme | Evet | Evet | Evet |
| PRD/şirket taslağı kaydetme | Hayır | Evet | Evet |
| PRD/şirket yayınlama | Hayır | Hayır | Evet |
| Müşteri oluşturma/güncelleme/CSV aktarımı | Hayır | Evet | Evet |
| Müşteri silme | Hayır | Hayır | Evet |

Sunucu denetimi esastır; buton gizleme tek güvenlik katmanı değildir. Süper yönetici için mevcut proje yetki modeli korunur.

## 3. MENA analizinin teknik davranışı

1. Varsayılan mevcut Türkçe profildir. Roman Urdu ve Arabizi için kurumda MENA profili yayınlanmalıdır; Latin harflerinden güvenilir dil varsayımı yapılmaz.
2. Arap yazısı kontrolü yalnız güvenlik yönlendirmesidir. Urduca ile Arapçayı aynı dil saymaz; model satır bazında dil etiketi üretir.
3. MENA yolunda orijinal yorum 600 karaktere kısaltılmaz. En fazla 6.000 karakter kabul edilir; aşım sessiz kırpılmaz.
4. Türkçe anahtar kelime, perspektif ve semantik düzeltme katmanları MENA sonucunu değiştirmez. Kesin insan düzeltmesi yolu korunur.
5. Satır sayısı/indeksi, benzersizlik, kategori kodu, duygu ve sayısal aralıklar doğrulanır. Eksik satır nötr sayılmaz.
6. MENA motorunda her sağlayıcı çağrısı en fazla 10 yorum; aynı işin paylaştığı motor için en fazla 3 eşzamanlı çağrı vardır. Bu sınır hesap genelinde dağıtık kota yöneticisi değildir; birden çok iş/worker toplam yükü ayrıca izlenmelidir.
7. MENA sağlayıcı isteği 45 saniyelik timeout kullanır. Google SDK iç tekrarları tek girişimle sınırlanır; uygulamanın mevcut tekrar politikası ayrıca geçerlidir. İptal/hata durumunda alt görevler iptal edilip beklenir, istemci kapatılır.
8. Sağlayıcı çalışmıyorsa MENA yorumları Türkçe BERT'e düşmez. Manuel istekte açıklayıcı hata, toplu işte hata yolu kullanılır; sahte başarı yazılmaz.
9. Dil belirsiz/kapsam dışıysa güven düşürülür. MENA güveni 0,6 altındaysa insan kontrolü gerekir ve otomatik ticket açılmaz. Yeni churn/süreç sinyallerine bu kayıtlar katılmaz. Mevcut platformun tüm eski grafiklerinin yeniden tasarlandığı iddia edilmez.
10. `customer_external_id`, `analysis_profile`, `analysis_language` review üzerinde saklanır. Manuel analiz, toplu yükleme ve yeniden analiz bağlantıları güncellenmiştir.

Mevcut sağlayıcı adaptörleri ve kurum model tercihleri korunmuştur. Araştırmadaki her aday için yeni adaptör eklenmemiştir. OpenAI/JAIS/çeviri ürünleri araştırma adaylarıdır; otomatik devreye alınmaz. Google SDK minimumu `google-genai>=1.75,<2.0` olarak güncellendi; yeni timeout/retry sözleşmesinin runtime imajına girmesi için yeniden build gerekir.

## 4. Veritabanı ve API

Migration: `0051_company_intelligence`, öncül `0050`. Üç yeni tenant tablosu:

- `intelligence_revisions`: PRD ve şirket dokümanının değiştirilmeyen sürüm içerikleri, durum, aktör, zaman.
- `customer_accounts`: kurum ve kanonik dış kimlik bazında güncel müşteri gözlemi.
- `customer_observations`: aynı müşterinin gözlem/risk geçmişi ve sürümü.

Yeni tablolar uygulamanın RLS/FORCE, tenant bağlama ve app/admin izin düzenini izler. Review tablosuna yukarıdaki üç nullable alan ve müşteri/tarih erişimi için kısmi indeks eklenmiştir. Eski yorumlar otomatik yeniden analiz edilmez veya müşterilere tahmini eşlenmez.

API kökü: `/tenants/me/intelligence`.

| Yöntem | Yol | Amaç |
|---|---|---|
| GET / PUT | `/documents/{prd|company}` | Son belge / beklenen sürümle kayıt |
| GET | `/documents/{kind}/history?before=...` | 20 sürümlük geçmiş sayfası |
| GET | `/prd/export` | Son kaydın Markdown çıktısı |
| GET | `/company/diagnostics` | Son yayınlı bağlamla bulgular |
| GET | `/customers?search=...&band=...&page=...` | Liste, toplamlar, risk dağılımı |
| PUT / DELETE | `/customers/{external_id}` | Müşteri güncelleme / yönetici silme |
| GET | `/customers/{external_id}/history?before=...` | Gözlem geçmişi |
| GET | `/customer-import/template` | CSV şablonu |
| POST | `/customer-import` | Doğrulanmış atomik aktarım |

Kayıt gövdeleri `expected_revision` taşır; ilk kayıt sıfırdır. Şirket/PRD için `status` ve `content`, müşteri için `profile` kullanılır. Tenant kimliği kullanıcı gövdesinden güvenilerek alınmaz, doğrulanmış oturumdan gelir.

## 5. Doğrulama

Testler gerçek üretim verisi veya ücretli model çağrısı kullanmadan çalıştırıldı. PostgreSQL testi `127.0.0.1:5433` üzerindeki izole `imga-codex-test-pg` konteynerinde yapıldı; geliştirme/üretim 5432 veritabanına migration uygulanmadı.

| Kontrol | Sonuç / kapsam |
|---|---|
| Boş PostgreSQL kurulumunda Alembic | Mevcut migration zinciri ve 0051 başarıyla uygulandı |
| Geniş API regresyonu | 117 test geçti: intelligence, SWOT, OKR, yeniden analiz ve kök neden |
| Son intelligence kontrolleri | 19 test geçti; kategori yayın doğrulaması ve 64 KiB sınırı dahil |
| Son birleşik API kontrolü | Intelligence + paralel batch + takılma regresyonu: 30 test geçti; proje aralığındaki SSE bağımlılığıyla tekrarlandı |
| Core sınıflandırıcı + MENA | 35 test geçti; katı yanıt, Türkçe koruma, dil/uzun metin ve sağlayıcı taklidi |
| Önceki hedefli API grupları | Dosya ayrıştırma/dimensions dahil 73; manuel analiz/paralel iş/takılma regresyonu dahil 46 test geçti |
| Gerçek DB, 3.000 müşteri CSV | Ekleme, liste son sayfası, güncelleme ve gözlem geçmişi doğrulandı |
| MENA, 3.000 sentetik yorum | Taklit sağlayıcıyla ortak eşzamanlılık sınırı 3 ve satır kapsamı doğrulandı |
| RLS/FORCE | App rolüyle tenant WHERE filtresi olmadan çapraz okuma izolasyonu; çapraz yazma reddi |
| Playwright | Gerçek API ile 4 senaryo geçti: PRD, şirket yayını/taslağı, müşteri risk/takip/geçmiş, viewer yetkisi |
| Görsel kontrol | 390×844 mobil ve masaüstü ekran görüntüleri incelendi; sayfa taşması kontrolleri geçti |
| TypeScript / Next production build | Başarılı; yeni üç route üretim derlemesine dahil |
| ESLint / Ruff | Hedeflenen yeni ve değişen dosyalarda başarılı |
| Mypy strict | Beş yeni API üretim modülünde başarılı |

Bu sayılar farklı komut gruplarıdır ve örtüşür; tekil test toplamı olarak toplanmamalıdır. Bütün depo testlerinin veya tam CI matrisinin çalıştırıldığı iddia edilmez. Test bağımlılıklarında deprecation uyarıları vardır; hedefli koşuları başarısız kılmamıştır. Windows test ortamında `--timeout-method=thread` kullanıldı.

Önemli ayrım: gerçek veritabanındaki 3.000 müşteri CSV aktarımı, 3.000 yorumun gerçek LLM ile analiz edilmesi değildir. Eski üretim takılması tamamen çözüldü sonucuna bu testlerden gidilemez. Gerçek sağlayıcıyla kota, bellek, süre ve iptal/yeniden başlatma testleri ayrıca gerekir.

## 6. Yerel önizleme

- Uygulama: [http://localhost:3000](http://localhost:3000).
- API: [http://127.0.0.1:8003/docs](http://127.0.0.1:8003/docs).
- İzole demo hesabı: `alice@acme.com`, parola `dev123`, kurum `Acme Inc.`.
- Bunlar yalnız yerel test veritabanının demo bilgileridir; üretim hesabı değildir.
- Demo kurumda MENA profili ve Arapça rapor dili yayınlandı; sonraki organizasyon değişiklikleri taslakta bırakıldı.
- Model anahtarı yapılandırılmadı. PRD/şirket/churn ekranları çalışır; gerçek MENA analizi için uygun kurum sağlayıcısı ve anahtarı gerekir.
- Yerel Redis/ARQ worker başlatılmadı. Önizlemedeki yönetim ekranları gerçek API kullanır; bu ortam üretim worker yük testi değildir.

Test ekran görüntüleri `packages/imga-web/test-results/intelligence-*.png` altında oluşur. Playwright bu klasörü sonraki çalıştırmada yenileyebilir; kalıcı rapor dosyaları bu klasöre bağlı değildir.

## 7. Staging / üretim açılışı

1. Veritabanı yedeği ve geri dönüş planı hazırla. Yeni migration'ın tablo oluşturduğunu, review alanlarını ve indeksini eklediğini kontrol et; downgrade bu çalışma kapsamında denenmedi.
2. Önce staging'de eski kodu kullanan API ve `api-worker` işlerini kontrollü durdur veya bakım penceresine al. Devam eden batch'leri ortada kesmeden boşalt.
3. Projenin mevcut Dockerfile ve bağımlılık sırasıyla API imajını yeniden build et. API ve `api-worker` aynı yeni imajı kullanmalıdır. Web imajını ayrıca build et.
4. Yeni imajdan, yalnız owner bağlantısıyla `alembic upgrade head` çalıştır. Uygulama rolüne DDL veya RLS bypass yetkisi verme. Migration otomatik başlangıca eklenmedi.
5. API, `api-worker` ve web'i yeni imajlarla aç. API/worker logları, healthcheck ve migration head kontrolünü yap.
6. Önce Türkçe kontrol kurumunu test et. Ardından sadece MENA pilot kurumunda şirket profilini yayınla ve sağlayıcı/model ayarını doğrula.
7. 98, 1.000 ve 3.000 yorum gerçek sağlayıcı testini; native değerlendiricilerin etiketli testini; saklama/veri aktarımı hukuk kontrolünü tamamla.
8. Hatalı sınıflandırma, insan inceleme oranı, kategori eşleme oranı, maliyet ve p95 süre için kabul kapıları geçilince üretimi kademeli aç.

Bu çalışma üretime dağıtılmadı, mevcut üretim anahtarlarını değiştirmedi ve git commit oluşturmadı. Çalışma ağacındaki başka geliştirmeler geri alınmadı. Dağıtım öncesi birlikte merge edilecek değişiklikler için tam CI ayrıca çalıştırılmalıdır.

## 8. Öncelikli devam işleri

1. Ana dil uzmanlarıyla etiketli Suudi/Emirlik Arapçası, Urduca, Roman Urdu ve Arabizi test kümesi; model sürümü bazında karşılaştırma ve onay kaydı.
2. CRM için otomatik gözlem akışı, kararlı müşteri kimlikleri ve veri tazeliği SLA'sı. Şimdilik manuel/CSV güncelleme gereklidir.
3. Gerçek müşteri-zaman kayıp etiketleri; zamansal doğrulamalı churn modeli. Öncelik puanının olasılıkla değiştirilmesi ayrı kabul gerektirir.
4. Olay bazlı süreç verisi ve yeterli örneklemle daha güçlü anomali analizi. Mevcut kategori eşlemesi süreç izi yerine geçmez.
5. Dağıtık sağlayıcı kota kontrolü, iş başına maliyet bütçesi ve gerçek worker bellek profili. İş içi 3 çağrı sınırı tek başına bütün worker'ları sınırlamaz.
6. Ülke ve müşteri sözleşmesine göre veri işleme yeri, saklama, silme ve sağlayıcı şartları. Mevcut müşteri silme tüm platform için KVKK/PDPL silme işlemi değildir.
