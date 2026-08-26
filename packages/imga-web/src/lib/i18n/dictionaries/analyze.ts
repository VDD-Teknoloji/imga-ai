import type { Bundle } from "./types";

/** analyze alan sözlüğü (Sprint 12 i18n): Manuel Analiz + Toplu Yükleme. */
export const analyze: Bundle = {
  tr: {
    // --- Manuel Analiz (analyze/page.tsx) ---
    "analyze.manual.title": "Yorum Analiz Et",
    "analyze.manual.subtitle":
      "Müşteri yorumunu yapıştırın. Duygu ve kategori analizi yapılır; kurum otomasyon ayarına göre gerekirse Ticket otomatik açılır.",
    "analyze.manual.textLabel": "Yorum metni",
    "analyze.manual.textPlaceholder":
      "Örnek: Kargom 5 gündür gelmedi, takip numarası da çalışmıyor.",
    "analyze.manual.charCount": "{count} / {max} karakter",
    "analyze.manual.npsLabel": "NPS (opsiyonel, 0–10)",
    "analyze.manual.analyzing": "Analiz ediliyor...",
    "analyze.manual.submit": "Analiz Et",
    "analyze.manual.newAnalysis": "Yeni analiz",
    "analyze.manual.npsRange": "NPS 0 ile 10 arasında olmalı.",
    "analyze.manual.textTooLong": "Metin 10.000 karakteri aşıyor.",
    "analyze.manual.noPermission": "Bu işlem için yetkin yok.",
    "analyze.manual.analyzeFailed": "Analiz tamamlanamadı.",
    "analyze.manual.triggeredLayers": "Tetiklenen Katmanlar",
    "analyze.manual.hideDetails": "Detayları Gizle",
    "analyze.manual.showDetails": "Detayları Göster",
    "analyze.manual.resultTitle": "Analiz sonucu",
    "analyze.manual.sentiment": "Duygu",
    "analyze.manual.category": "Kategori",
    "analyze.manual.confidenceSuffix": "%{pct} güven",
    "analyze.manual.companyPerspective": "Şirket perspektifi",
    "analyze.manual.noMatch": "eşleşme yok",
    "analyze.manual.summary": "Özet",
    "analyze.manual.promoteSuccess": "Manuel olarak Ticket açıldı.",
    "analyze.manual.alreadyLinked": "Bu analiz zaten bir Ticket'a bağlı.",
    "analyze.manual.categoryNotConfigured":
      "Kategori bu kurumda yapılandırılmamış — Ticket açılamadı.",
    "analyze.manual.promoteFailed": "Ticket açılamadı.",
    "analyze.manual.goNewTicket": "Yeni Ticket'a git",
    "analyze.manual.goExistingTicket": "Mevcut Ticket'a git",
    "analyze.manual.ticketIdLabel": "Ticket ID:",
    "analyze.manual.promoteAnyway": "Yine de Ticket Aç",
    "analyze.manual.promoteHint":
      "Sistem güvenini geçersiz kıl — manuel olarak Ticket aç.",
    "analyze.manual.decision.create.title": "Otomatik Ticket açıldı",
    "analyze.manual.decision.create.message":
      "Kurumunuzun otomasyon ayarı bu yoruma göre yeni bir Ticket açtı.",
    "analyze.manual.decision.dedup.title":
      "Aynı metin son 24 saatte zaten analiz edildi",
    "analyze.manual.decision.dedup.message":
      "Tekrar Ticket açılmadı; mevcut Ticket'ın altında çalışmaya devam et.",
    "analyze.manual.decision.mode.title":
      "Otomasyon modu manuel — Ticket açılmadı",
    "analyze.manual.decision.mode.message":
      "Manuel modda yalnızca duygu ve kategori analizi yapılır; Ticket açma için kurum ayarlarını Tam veya Yarı otomatik yap.",
    "analyze.manual.decision.threshold.title": "Eşik altı — Ticket açılmadı",
    "analyze.manual.decision.threshold.message":
      "Kurum otomasyon eşiği bu yorumu otomatik Ticket açmak için yeterli bulmadı; metni manuel inceleyebilirsin.",
    "analyze.manual.decision.belirsiz.title":
      "Kategori belirsiz — manuel sınıflandırma gerekli",
    "analyze.manual.decision.belirsiz.message":
      "Sınıflandırıcı bu metni emin bir kategoriye yerleştiremedi. Hangi modda olursan ol, belirsiz yorumlardan otomatik Ticket açılmaz.",
    "analyze.manual.decision.quality.title":
      "Düşük kaliteli veri — Ticket açılmadı",
    "analyze.manual.decision.quality.message":
      "Bu metin gerçek bir müşteri yorumu olarak değerlendirilmedi (boş/anlamsız veya otomatik bilgilendirme). Analiz kaydı tutuldu; varsayılan grafiklerde hariç tutulur.",

    // --- Toplu Yükleme (analyze/upload/page.tsx) ---
    "analyze.upload.backManual": "Manuel Analiz",
    "analyze.upload.title": "Toplu Yükleme",
    "analyze.upload.subtitle":
      "CSV ya da XLSX yükleyin; metinler arka planda analiz edilir, sonuç Analiz Arşivi'nde görünür.",
    "analyze.upload.step.file": "Dosya",
    "analyze.upload.step.columns": "Sütunlar",
    "analyze.upload.step.progress": "İlerleme",
    "analyze.upload.step.done": "Tamamlandı",
    "analyze.upload.reconnected":
      "Devam eden yükleme bulundu ({file}) — ilerlemeye yeniden bağlanıldı.",
    "analyze.upload.previewFailedDetail": "Önizleme alınamadı: {detail}",
    "analyze.upload.previewFailed": "Önizleme alınamadı.",
    "analyze.upload.uploadError": "Yükleme sırasında hata oluştu.",
    "analyze.upload.cancelFailed": "İptal başarısız.",
    "analyze.upload.template.heading":
      "İlk defa mı yüklüyorsunuz? Önce şablonu indirin.",
    "analyze.upload.template.bodyBefore": "Yorumlarınızı şablondaki ",
    "analyze.upload.template.bodyAfter":
      " kolonuna yapıştırın. Şablona uymayan dosyalar reddedilir.",
    "analyze.upload.template.dateHint":
      "Dosyadaki tarih kolonu yorumun kendi tarihi olarak kullanılır — " +
      "analizler ve trendler bu tarihe göre gruplanır. Boşsa yükleme " +
      "zamanı kullanılır. Biçim: YYYY-AA-GG veya gg.aa.yyyy.",
    "analyze.upload.template.downloadFailedRetry":
      "Şablon indirilemedi. Lütfen daha sonra tekrar deneyin.",
    "analyze.upload.template.downloadFailed": "Şablon indirilemedi.",
    "analyze.upload.template.download": "Şablonu İndir",
    "analyze.upload.step1Title": "Adım 1 — Dosya Seç",
    "analyze.upload.onlyCsvXlsx": "Sadece .csv veya .xlsx dosyaları kabul edilir.",
    "analyze.upload.fileTooLarge": "Dosya 50 MB sınırını aşıyor.",
    "analyze.upload.dropzone": "Dosyayı buraya bırakın veya tıklayarak seçin",
    "analyze.upload.dropzoneHint":
      "CSV, XLSX — en fazla 50 MB, en fazla 25.000 satır",
    "analyze.upload.step2Title": "Adım 2 — Sütun Eşleştirme",
    "analyze.upload.rowCount": "{n} satır",
    "analyze.upload.analyzingColumns": "Sütunlar analiz ediliyor…",
    "analyze.upload.noAutoDetect":
      "Otomatik tespit alınamadı; yorum sütunu yükleme sırasında sunucu tarafından belirlenecek.",
    "analyze.upload.autoCreateTitle": "Otomatik Ticket aç",
    "analyze.upload.autoCreateHelp":
      "Kurumunuzun otomasyon modu ayarına göre eşiği geçen satırlar için otomatik Ticket açılır. Kapalıysa hiçbir satır Ticket açmaz; tüm analizler Analiz Arşivi'nde listelenir.",
    "analyze.upload.back": "Geri",
    "analyze.upload.fixErrorsTitle":
      "Dosyadaki engelleyici hataları düzeltip yeniden yükleyin",
    "analyze.upload.piiConsentFirst": "Önce PII onayı verin",
    "analyze.upload.uploading": "Yükleniyor…",
    "analyze.upload.startUpload": "Yüklemeyi Başlat",
    "analyze.upload.loadingJob": "Yükleme bilgisi yükleniyor…",
    "analyze.upload.step3Title": "Adım 3 — İlerleme",
    "analyze.upload.stat.processed": "İşlenen",
    "analyze.upload.stat.succeeded": "Başarılı",
    "analyze.upload.stat.failed": "Hatalı",
    "analyze.upload.stat.duplicates": "Tekrar",
    "analyze.upload.stat.tickets": "Ticket",
    "analyze.upload.estimatedTime": "Kalan tahmini süre: ~{n} dakika",
    "analyze.upload.cancel": "İptal Et",
    "analyze.upload.step4Prefix": "Adım 4 — ",
    "analyze.upload.errorSummary": "Hata özeti ({n})",
    "analyze.upload.rowPrefix": "Satır {n}:",
    "analyze.upload.general": "Genel:",
    "analyze.upload.viewAnalyses": "Bu Yüklemenin Analizlerini Gör",
    "analyze.upload.openReviewList": "Yorum listesini aç",
    "analyze.upload.newUpload": "Yeni Yükleme",
    "analyze.upload.validation.cannotUpload": "Bu dosya yüklenemez",
    "analyze.upload.validation.okBefore": "Dosya şablona uygun — ",
    "analyze.upload.validation.okAfter": " satır analiz edilecek.",
    "analyze.upload.validation.warnSummary":
      "{valid} satır analiz edilecek · {warn} satır atlanacak",
    "analyze.upload.validation.warnFooter":
      "Bu satırları yine de yükleyebilirsiniz; atlanan satırlar analiz edilmez.",
    "analyze.upload.status.completed": "Tamamlandı",
    "analyze.upload.status.failed": "Başarısız",
    "analyze.upload.status.cancelled": "İptal edildi",
    "analyze.upload.status.processing": "İşleniyor",
    "analyze.upload.status.queued": "Sıraya alındı",

    // --- 2026-08-18 (Dalga 3, WS2): Adım 4 Veri Kalitesi kartı ---
    "analyze.upload.quality.title": "Veri Kalitesi",
    "analyze.upload.quality.validCount": "{n} temiz satır",
    "analyze.upload.quality.duplicate": "Tekrar",
    "analyze.upload.quality.empty": "Boş",
    "analyze.upload.quality.informational": "Bilgilendirme",
    "analyze.upload.quality.meaningless": "Anlamsız",

    // --- Twitter'dan Çek (analyze/twitter/page.tsx) ---
    "analyze.twitter.back": "Toplu Yükleme",
    "analyze.twitter.title": "Twitter'dan Çek",
    "analyze.twitter.subtitle":
      "X/Twitter'da markanız hakkında yazılan Türkçe gönderileri çekin; metinler toplu yükleme ile aynı boru hattında analiz edilir.",
    "analyze.twitter.formTitle": "Arama",
    "analyze.twitter.brandLabel": "Marka / şirket adı",
    "analyze.twitter.brandPlaceholder": "Örn. Karaca",
    "analyze.twitter.brandHelp":
      "AI bu addan ve kurum profilinizden (sektör, iş tanımı) arama terimlerini çıkarır; aynı adı taşıyan kişi, yer ve şarkıları hariç tutar.",
    "analyze.twitter.planButton": "AI ile anahtar kelimeleri çıkar",
    "analyze.twitter.planning": "Anahtar kelimeler çıkarılıyor…",
    "analyze.twitter.planDone":
      "Anahtar kelimeler çıkarıldı — listeyi kontrol edip düzenleyebilirsiniz.",
    "analyze.twitter.planFailed": "Anahtar kelimeler çıkarılamadı, lütfen tekrar deneyin.",
    "analyze.twitter.planNoKeys":
      "Aktif LLM anahtarı yok — Ayarlar > Entegrasyonlar'dan ekleyin ya da terimleri elle yazın.",
    "analyze.twitter.planBrandRequired": "Önce marka adını yazın.",
    "analyze.twitter.summaryLabel": "AI marka özeti",
    "analyze.twitter.includeLabel": "Dahil edilen terimler",
    "analyze.twitter.excludeTermsLabel": "Hariç tutulanlar",
    "analyze.twitter.ambiguousNote":
      "Marka adı tek başına belirsiz (yaygın soyadı/kelime); AI terimleri ürün ve hesap birleşimleriyle kurdu.",
    "analyze.twitter.queryPreview": "X sorgusu",
    "analyze.twitter.termLabel": "Arama terimleri",
    "analyze.twitter.termPlaceholder": "Örn. karaca tencere, @karacaonline, -cem karaca",
    "analyze.twitter.termHelp":
      "Gönderi metinlerinde aranır. Virgülle birden çok terim yazabilirsiniz; başına - koyduklarınız hariç tutulur. AI planı bu alanı doldurur, dilediğiniz gibi düzenleyin.",
    "analyze.twitter.relevanceLabel": "AI alaka kontrolü",
    "analyze.twitter.relevanceHelp":
      "Çekilen her gönderi \"bu marka hakkında mı?\" diye AI'a sorulur; alakasızlar arşive girmeden elenir. Yaygın soyadı/kelime olan markalar için önerilir.",
    "analyze.twitter.countLabel": "Kaç gönderi çekilsin?",
    "analyze.twitter.countOption": "{n} gönderi",
    "analyze.twitter.excludeLabel": "Hariç tutulacak hesap (opsiyonel)",
    "analyze.twitter.excludePlaceholder": "resmi hesabınız",
    "analyze.twitter.excludeHelp":
      "Resmi hesabınızın kendi paylaşımları müşteri sesi değildir; kullanıcı adını yazarsanız elenir. Bu hesaba yazılan yanıtlar ise korunur.",
    "analyze.twitter.infoTitle": "Nasıl çalışır?",
    "analyze.twitter.info":
      "En yeni Türkçe gönderiler çekilir (retweet'ler hariç), bağlantılar temizlenir, kopyalar elenir ve sonuç Toplu Yükleme ilerleme ekranına düşer. X araması yazar adında da eşleştiğinden, metninde terim geçmeyen ve resmi hesaba yazılmamış gönderiler elenir. Her yorum tweet bağlantısıyla Analiz Arşivi'ne düşer; analizler diğer yüklemeler gibi arşivde ve ana sayfa yükleme filtresinde görünür.",
    "analyze.twitter.durationHint":
      "Çekim, istenen sayıya ve AI kontrolüne göre 30 saniye – birkaç dakika sürebilir.",
    "analyze.twitter.submit": "Çek ve Analiz Et",
    "analyze.twitter.submitting": "Gönderiler çekiliyor…",
    "analyze.twitter.queued": "{found} gönderi bulundu — analiz kuyruğa alındı.",
    "analyze.twitter.filteredNote": " {n} alakasız gönderi elendi.",
    "analyze.twitter.aiFilteredNote": " AI alaka kontrolü {n} gönderiyi eledi.",
    "analyze.twitter.aiSkippedNote": " (AI alaka kontrolü çalışmadı — LLM anahtarı yok ya da hata.)",
    "analyze.twitter.queuedPartial":
      "{found} gönderi bulundu (X'te bu arama için daha fazla Türkçe sonuç yok) — analiz kuyruğa alındı.",
    "analyze.twitter.notConfigured":
      "Twitter entegrasyonu henüz bu sunucuda yapılandırılmamış. Sistem yöneticinize başvurun.",
    "analyze.twitter.failed": "Gönderiler çekilemedi, lütfen tekrar deneyin.",
    "analyze.twitter.termRequired": "Arama terimi en az 2 karakter olmalı.",

    // --- Geçmiş Yüklemeler (analyze/upload/history/page.tsx) ---
    "analyze.history.backUpload": "Toplu Yükleme",
    "analyze.history.title": "Geçmiş Yüklemeler",
    "analyze.history.newUpload": "Yeni Yükleme",
    "analyze.history.loading": "Yükleniyor…",
    "analyze.history.emptyBefore": "Henüz toplu yükleme yok. İlk dosyanızı ",
    "analyze.history.emptyLink": "buradan",
    "analyze.history.emptyAfter": " yükleyebilirsiniz.",
    "analyze.history.retry": "Tekrar Dene",
    "analyze.history.retryQueued":
      "Yükleme kuyruğa alındı — kaldığı satırdan devam edecek.",
    "analyze.history.retryFailed": "Tekrar deneme başarısız.",
    "analyze.history.col.date": "Tarih",
    "analyze.history.col.file": "Dosya",
    "analyze.history.col.rows": "Satır",
    "analyze.history.col.status": "Durum",
    "analyze.history.col.succeeded": "Başarılı",
    "analyze.history.col.failed": "Hata",
    "analyze.history.col.tickets": "Ticket",
    "analyze.history.viewAnalyses": "Analizleri gör →",
    "analyze.history.loadMore": "Daha fazla göster",
    "analyze.history.status.queued": "Sırada",
    "analyze.history.status.processing": "İşleniyor",
    "analyze.history.status.completed": "Tamamlandı",
    "analyze.history.status.failed": "Başarısız",
    "analyze.history.status.cancelled": "İptal",

    // --- 2026-08-18 (Dalga 3, WS2): Kalite Raporu paneli ---
    "analyze.history.qualityReport.action": "Kalite Raporu",
    "analyze.history.qualityReport.title": "Veri Kalitesi Raporu",
    "analyze.history.qualityReport.subtitle":
      "Bu yüklemenin bayrak sayaçları, en çok tekrarlanan metinler ve çalışan bazlı kırılım.",
    "analyze.history.qualityReport.duplicate": "Tekrar",
    "analyze.history.qualityReport.empty": "Boş",
    "analyze.history.qualityReport.informational": "Bilgilendirme",
    "analyze.history.qualityReport.meaningless": "Anlamsız",
    "analyze.history.qualityReport.topRepeatedTitle": "En Çok Tekrarlanan Metinler",
    "analyze.history.qualityReport.byEmployeeTitle": "Çalışan Bazlı Kırılım",
    "analyze.history.qualityReport.col.text": "Metin",
    "analyze.history.qualityReport.col.count": "Adet",
    "analyze.history.qualityReport.col.employee": "Çalışan",
    "analyze.history.qualityReport.col.total": "Toplam",
    "analyze.history.qualityReport.unknownEmployee": "Bilinmiyor",
    "analyze.history.qualityReport.aiAssessmentTitle": "Yapay Zekâ Değerlendirmesi",
    "analyze.history.qualityReport.notGeneratedYet":
      "Bu yükleme için henüz bir değerlendirme üretilmedi.",
    "analyze.history.qualityReport.notGeneratedYetViewer":
      "Bu yükleme için henüz bir değerlendirme üretilmedi.",
    "analyze.history.qualityReport.generateButton": "Değerlendirme Üret",
    "analyze.history.qualityReport.generating": "Değerlendirme üretiliyor…",
    "analyze.history.qualityReport.generatedMeta": "{model} · {date}",
    "analyze.history.qualityReport.generateFailed":
      "Değerlendirme üretilemedi.",
    "analyze.history.qualityReport.loadFailed": "Kalite raporu yüklenemedi.",
    "analyze.history.qualityReport.close": "Kapat",

    // --- Yeniden analiz (yalnız kurum yöneticisi) ---
    "analyze.history.reanalyze.action": "Yeniden Analiz Et",
    "analyze.history.reanalyze.confirmTitle": "Yeniden analiz edilsin mi?",
    "analyze.history.reanalyze.confirmDesc":
      "Bu yüklemenin {count} yorumu yeni sınıflandırma kurallarıyla yeniden analiz edilecek; insan düzeltmeleri korunur. Sürebilir.",
    "analyze.history.reanalyze.confirm": "Yeniden analiz et",
    "analyze.history.reanalyze.cancel": "Vazgeç",
    "analyze.history.reanalyze.submitting": "Kuyruğa alınıyor…",
    "analyze.history.reanalyze.queued": "Yeniden analiz kuyruğa alındı",
    "analyze.history.reanalyze.failed": "Yeniden analiz başlatılamadı.",
    "analyze.history.reanalyze.noPermission":
      "Yeniden analiz için kurum yöneticisi olmanız gerekir.",
    "analyze.history.reanalyze.allButton": "Tüm yorumları yeniden analiz et",
    "analyze.history.reanalyze.allConfirmTitle":
      "Kurumun tüm yorumları yeniden analiz edilsin mi?",
    "analyze.history.reanalyze.allConfirmDesc":
      "Kurumdaki TÜM yorumlar yeni sınıflandırma kurallarıyla baştan analiz edilecek; insan düzeltmeleri korunur. Veri hacmine göre uzun sürebilir ve bu süre boyunca analiz sonuçları değişmeye devam eder. Tek bir yüklemeyi güncellemek istiyorsanız satır bazındaki Yeniden Analiz Et'i kullanın.",
    "analyze.history.reanalyze.allConfirm": "Evet, tümünü yeniden analiz et",

    // --- Sütun eşleme (components/analyze/column-mapping-preview.tsx) ---
    "analyze.mapping.hint":
      'Sütun açıklamasına tıklayarak elle değiştirebilirsiniz. "Yoksay" seçilen sütunlar yüklemeye dahil edilmez.',
    "analyze.mapping.manuallyChanged": "elle değiştirildi",
    "analyze.mapping.autoDetectedInline": "(otomatik tespit)",
    "analyze.mapping.sampleLabel": "Örnek: ",
    "analyze.mapping.alternativeLabel": "Alternatif tespit: ",
    "analyze.mapping.noRows": "Önizleme için satır yok.",

    // --- Güven rozeti (components/analyze/confidence-badge.tsx) ---
    "analyze.confidence.high": "Yüksek güven",
    "analyze.confidence.medium": "Orta güven",
    "analyze.confidence.low": "Düşük güven — lütfen kontrol edin",

    // --- PII uyarısı (components/analyze/pii-warning-banner.tsx) ---
    "analyze.pii.heading":
      "Bu dosyada kişisel veri içerebilecek sütun(lar) bulundu.",
    "analyze.pii.detectedColumns": "Tespit edilen sütun(lar): ",
    "analyze.pii.body":
      "Bu sütunlardaki değerler analiz sürecinde işlenecek ve ilgili kurumun veri kayıtlarında saklanabilir. KVKK uyarınca yüklemeye devam etmek için aşağıdaki onayı işaretleyin.",
    "analyze.pii.consent":
      "Bu kolonlardaki kişisel verilerin işlenmesine onay veriyorum.",
  },
  en: {
    // --- Manual Analysis (analyze/page.tsx) ---
    "analyze.manual.title": "Analyze Comment",
    "analyze.manual.subtitle":
      "Paste a customer comment. Sentiment and category analysis runs; depending on your organization's automation setting, a Ticket may be opened automatically.",
    "analyze.manual.textLabel": "Comment text",
    "analyze.manual.textPlaceholder":
      "Example: My package hasn't arrived for 5 days, and the tracking number doesn't work either.",
    "analyze.manual.charCount": "{count} / {max} characters",
    "analyze.manual.npsLabel": "NPS (optional, 0–10)",
    "analyze.manual.analyzing": "Analyzing...",
    "analyze.manual.submit": "Analyze",
    "analyze.manual.newAnalysis": "New analysis",
    "analyze.manual.npsRange": "NPS must be between 0 and 10.",
    "analyze.manual.textTooLong": "Text exceeds 10,000 characters.",
    "analyze.manual.noPermission": "You don't have permission for this action.",
    "analyze.manual.analyzeFailed": "Analysis could not be completed.",
    "analyze.manual.triggeredLayers": "Triggered Layers",
    "analyze.manual.hideDetails": "Hide Details",
    "analyze.manual.showDetails": "Show Details",
    "analyze.manual.resultTitle": "Analysis result",
    "analyze.manual.sentiment": "Sentiment",
    "analyze.manual.category": "Category",
    "analyze.manual.confidenceSuffix": "{pct}% confidence",
    "analyze.manual.companyPerspective": "Company perspective",
    "analyze.manual.noMatch": "no match",
    "analyze.manual.summary": "Summary",
    "analyze.manual.promoteSuccess": "Ticket opened manually.",
    "analyze.manual.alreadyLinked":
      "This analysis is already linked to a Ticket.",
    "analyze.manual.categoryNotConfigured":
      "Category is not configured for this organization — could not open a Ticket.",
    "analyze.manual.promoteFailed": "Ticket could not be opened.",
    "analyze.manual.goNewTicket": "Go to new Ticket",
    "analyze.manual.goExistingTicket": "Go to existing Ticket",
    "analyze.manual.ticketIdLabel": "Ticket ID:",
    "analyze.manual.promoteAnyway": "Open Ticket Anyway",
    "analyze.manual.promoteHint":
      "Override the system's confidence — open a Ticket manually.",
    "analyze.manual.decision.create.title": "Ticket opened automatically",
    "analyze.manual.decision.create.message":
      "Your organization's automation setting opened a new Ticket for this comment.",
    "analyze.manual.decision.dedup.title":
      "The same text was already analyzed in the last 24 hours",
    "analyze.manual.decision.dedup.message":
      "No new Ticket was opened; continue working under the existing Ticket.",
    "analyze.manual.decision.mode.title":
      "Automation mode is manual — no Ticket opened",
    "analyze.manual.decision.mode.message":
      "In manual mode only sentiment and category analysis runs; to open Tickets, set your organization to Full or Semi-automatic.",
    "analyze.manual.decision.threshold.title":
      "Below threshold — no Ticket opened",
    "analyze.manual.decision.threshold.message":
      "The organization's automation threshold didn't find this comment sufficient to open a Ticket automatically; you can review the text manually.",
    "analyze.manual.decision.belirsiz.title":
      "Category unclear — manual classification required",
    "analyze.manual.decision.belirsiz.message":
      "The classifier couldn't confidently place this text in a category. Regardless of mode, unclear comments don't open Tickets automatically.",
    "analyze.manual.decision.quality.title":
      "Low-quality data — no Ticket opened",
    "analyze.manual.decision.quality.message":
      "This text wasn't treated as a genuine customer review (empty/meaningless or an automated notification). The analysis row is kept and excluded from default charts.",

    // --- Bulk Upload (analyze/upload/page.tsx) ---
    "analyze.upload.backManual": "Manual Analysis",
    "analyze.upload.title": "Bulk Upload",
    "analyze.upload.subtitle":
      "Upload a CSV or XLSX; texts are analyzed in the background and results appear in the Analysis Archive.",
    "analyze.upload.step.file": "File",
    "analyze.upload.step.columns": "Columns",
    "analyze.upload.step.progress": "Progress",
    "analyze.upload.step.done": "Completed",
    "analyze.upload.reconnected":
      "Found an in-progress upload ({file}) — reconnected to its progress.",
    "analyze.upload.previewFailedDetail": "Preview failed: {detail}",
    "analyze.upload.previewFailed": "Preview failed.",
    "analyze.upload.uploadError": "An error occurred during upload.",
    "analyze.upload.cancelFailed": "Cancellation failed.",
    "analyze.upload.template.heading":
      "First time uploading? Download the template first.",
    "analyze.upload.template.bodyBefore": "Paste your comments into the ",
    "analyze.upload.template.bodyAfter":
      " column of the template. Files that don't match the template are rejected.",
    "analyze.upload.template.dateHint":
      "The date column in your file is used as the review's own date — " +
      "analyses and trends are grouped by it. Left empty, the upload " +
      "time is used. Format: YYYY-MM-DD or dd.mm.yyyy.",
    "analyze.upload.template.downloadFailedRetry":
      "Template could not be downloaded. Please try again later.",
    "analyze.upload.template.downloadFailed": "Template could not be downloaded.",
    "analyze.upload.template.download": "Download Template",
    "analyze.upload.step1Title": "Step 1 — Select File",
    "analyze.upload.onlyCsvXlsx": "Only .csv or .xlsx files are accepted.",
    "analyze.upload.fileTooLarge": "File exceeds the 50 MB limit.",
    "analyze.upload.dropzone": "Drop the file here or click to select",
    "analyze.upload.dropzoneHint":
      "CSV, XLSX — up to 50 MB, up to 25,000 rows",
    "analyze.upload.step2Title": "Step 2 — Column Mapping",
    "analyze.upload.rowCount": "{n} rows",
    "analyze.upload.analyzingColumns": "Analyzing columns…",
    "analyze.upload.noAutoDetect":
      "Automatic detection unavailable; the review column will be resolved server-side during upload.",
    "analyze.upload.autoCreateTitle": "Open Tickets automatically",
    "analyze.upload.autoCreateHelp":
      "Depending on your organization's automation mode, Tickets are opened automatically for rows that pass the threshold. If off, no row opens a Ticket; all analyses are listed in the Analysis Archive.",
    "analyze.upload.back": "Back",
    "analyze.upload.fixErrorsTitle":
      "Fix the blocking errors in the file and re-upload",
    "analyze.upload.piiConsentFirst": "Give PII consent first",
    "analyze.upload.uploading": "Uploading…",
    "analyze.upload.startUpload": "Start Upload",
    "analyze.upload.loadingJob": "Loading upload info…",
    "analyze.upload.step3Title": "Step 3 — Progress",
    "analyze.upload.stat.processed": "Processed",
    "analyze.upload.stat.succeeded": "Succeeded",
    "analyze.upload.stat.failed": "Failed",
    "analyze.upload.stat.duplicates": "Duplicates",
    "analyze.upload.stat.tickets": "Ticket",
    "analyze.upload.estimatedTime": "Estimated time left: ~{n} minutes",
    "analyze.upload.cancel": "Cancel",
    "analyze.upload.step4Prefix": "Step 4 — ",
    "analyze.upload.errorSummary": "Error summary ({n})",
    "analyze.upload.rowPrefix": "Row {n}:",
    "analyze.upload.general": "General:",
    "analyze.upload.viewAnalyses": "View This Upload's Analyses",
    "analyze.upload.openReviewList": "Open the review list",
    "analyze.upload.newUpload": "New Upload",
    "analyze.upload.validation.cannotUpload": "This file can't be uploaded",
    "analyze.upload.validation.okBefore": "File matches the template — ",
    "analyze.upload.validation.okAfter": " rows will be analyzed.",
    "analyze.upload.validation.warnSummary":
      "{valid} rows will be analyzed · {warn} rows will be skipped",
    "analyze.upload.validation.warnFooter":
      "You can still upload these; skipped rows won't be analyzed.",
    "analyze.upload.status.completed": "Completed",
    "analyze.upload.status.failed": "Failed",
    "analyze.upload.status.cancelled": "Cancelled",
    "analyze.upload.status.processing": "Processing",
    "analyze.upload.status.queued": "Queued",

    // --- 2026-08-18 (Wave 3, WS2): Step 4 Data Quality card ---
    "analyze.upload.quality.title": "Data Quality",
    "analyze.upload.quality.validCount": "{n} clean rows",
    "analyze.upload.quality.duplicate": "Duplicate",
    "analyze.upload.quality.empty": "Empty",
    "analyze.upload.quality.informational": "Informational",
    "analyze.upload.quality.meaningless": "Meaningless",

    // --- Import from Twitter (analyze/twitter/page.tsx) ---
    "analyze.twitter.back": "Bulk Upload",
    "analyze.twitter.title": "Import from Twitter",
    "analyze.twitter.subtitle":
      "Pull Turkish posts about your brand from X/Twitter; the texts run through the same pipeline as bulk uploads.",
    "analyze.twitter.formTitle": "Search",
    "analyze.twitter.brandLabel": "Brand / company name",
    "analyze.twitter.brandPlaceholder": "e.g. Karaca",
    "analyze.twitter.brandHelp":
      "The AI derives search terms from this name and your company profile (industry, description) and excludes namesake people, places and songs.",
    "analyze.twitter.planButton": "Extract keywords with AI",
    "analyze.twitter.planning": "Extracting keywords…",
    "analyze.twitter.planDone": "Keywords extracted — review and edit the list as needed.",
    "analyze.twitter.planFailed": "Could not extract keywords, please try again.",
    "analyze.twitter.planNoKeys":
      "No active LLM key — add one under Settings > Integrations or type the terms manually.",
    "analyze.twitter.planBrandRequired": "Enter the brand name first.",
    "analyze.twitter.summaryLabel": "AI brand summary",
    "analyze.twitter.includeLabel": "Included terms",
    "analyze.twitter.excludeTermsLabel": "Excluded",
    "analyze.twitter.ambiguousNote":
      "The bare brand name is ambiguous (a common surname/word); the AI built the terms from product and account combinations.",
    "analyze.twitter.queryPreview": "X query",
    "analyze.twitter.termLabel": "Search terms",
    "analyze.twitter.termPlaceholder": "e.g. karaca tencere, @karacaonline, -cem karaca",
    "analyze.twitter.termHelp":
      "Matched inside post texts. Separate several terms with commas; a leading - excludes a term. The AI plan fills this field — edit it freely.",
    "analyze.twitter.relevanceLabel": "AI relevance check",
    "analyze.twitter.relevanceHelp":
      "Every fetched post is asked \"is this about the brand?\"; unrelated ones are dropped before they reach the archive. Recommended for brands that are common surnames/words.",
    "analyze.twitter.countLabel": "How many posts?",
    "analyze.twitter.countOption": "{n} posts",
    "analyze.twitter.excludeLabel": "Account to exclude (optional)",
    "analyze.twitter.excludePlaceholder": "your official handle",
    "analyze.twitter.excludeHelp":
      "Your official account's own posts aren't customer voice; enter the handle to filter them out. Replies addressed to that account are kept.",
    "analyze.twitter.infoTitle": "How it works:",
    "analyze.twitter.info":
      "The most recent Turkish posts are fetched (retweets excluded), links are stripped, duplicates removed, and the result lands on the Bulk Upload progress screen. Because X search also matches author names, posts whose text doesn't contain the term and that aren't addressed to the official account are dropped. Every review lands in the Review Archive with its tweet link; analyses appear in the archive and the home-page upload filter like any other upload.",
    "analyze.twitter.durationHint":
      "Fetching takes 30 seconds to a few minutes depending on the requested count and the AI check.",
    "analyze.twitter.submit": "Fetch & Analyze",
    "analyze.twitter.submitting": "Fetching posts…",
    "analyze.twitter.queued": "{found} posts found — analysis queued.",
    "analyze.twitter.filteredNote": " {n} unrelated posts were dropped.",
    "analyze.twitter.aiFilteredNote": " The AI relevance check dropped {n} posts.",
    "analyze.twitter.aiSkippedNote": " (AI relevance check did not run — no LLM key or an error.)",
    "analyze.twitter.queuedPartial":
      "{found} posts found (no more Turkish results on X for this search) — analysis queued.",
    "analyze.twitter.notConfigured":
      "The Twitter integration is not configured on this server yet. Contact your system administrator.",
    "analyze.twitter.failed": "Could not fetch posts, please try again.",
    "analyze.twitter.termRequired": "The search term must be at least 2 characters.",

    // --- Past Uploads (analyze/upload/history/page.tsx) ---
    "analyze.history.backUpload": "Bulk Upload",
    "analyze.history.title": "Past Uploads",
    "analyze.history.newUpload": "New Upload",
    "analyze.history.loading": "Loading…",
    "analyze.history.emptyBefore":
      "No bulk uploads yet. You can upload your first file ",
    "analyze.history.emptyLink": "here",
    "analyze.history.emptyAfter": ".",
    "analyze.history.retry": "Retry",
    "analyze.history.retryQueued":
      "Upload queued — it will resume from where it left off.",
    "analyze.history.retryFailed": "Retry failed.",
    "analyze.history.col.date": "Date",
    "analyze.history.col.file": "File",
    "analyze.history.col.rows": "Rows",
    "analyze.history.col.status": "Status",
    "analyze.history.col.succeeded": "Succeeded",
    "analyze.history.col.failed": "Errors",
    "analyze.history.col.tickets": "Ticket",
    "analyze.history.viewAnalyses": "View analyses →",
    "analyze.history.loadMore": "Show more",
    "analyze.history.status.queued": "Queued",
    "analyze.history.status.processing": "Processing",
    "analyze.history.status.completed": "Completed",
    "analyze.history.status.failed": "Failed",
    "analyze.history.status.cancelled": "Cancelled",

    // --- 2026-08-18 (Wave 3, WS2): Quality Report panel ---
    "analyze.history.qualityReport.action": "Quality Report",
    "analyze.history.qualityReport.title": "Data Quality Report",
    "analyze.history.qualityReport.subtitle":
      "This upload's flag counts, most repeated texts, and per-employee breakdown.",
    "analyze.history.qualityReport.duplicate": "Duplicate",
    "analyze.history.qualityReport.empty": "Empty",
    "analyze.history.qualityReport.informational": "Informational",
    "analyze.history.qualityReport.meaningless": "Meaningless",
    "analyze.history.qualityReport.topRepeatedTitle": "Most Repeated Texts",
    "analyze.history.qualityReport.byEmployeeTitle": "Per-Employee Breakdown",
    "analyze.history.qualityReport.col.text": "Text",
    "analyze.history.qualityReport.col.count": "Count",
    "analyze.history.qualityReport.col.employee": "Employee",
    "analyze.history.qualityReport.col.total": "Total",
    "analyze.history.qualityReport.unknownEmployee": "Unknown",
    "analyze.history.qualityReport.aiAssessmentTitle": "AI Assessment",
    "analyze.history.qualityReport.notGeneratedYet":
      "No assessment has been generated for this upload yet.",
    "analyze.history.qualityReport.notGeneratedYetViewer":
      "No assessment has been generated for this upload yet.",
    "analyze.history.qualityReport.generateButton": "Generate Assessment",
    "analyze.history.qualityReport.generating": "Generating assessment…",
    "analyze.history.qualityReport.generatedMeta": "{model} · {date}",
    "analyze.history.qualityReport.generateFailed":
      "Could not generate the assessment.",
    "analyze.history.qualityReport.loadFailed": "Could not load the quality report.",
    "analyze.history.qualityReport.close": "Close",

    // --- Re-analysis (tenant admin only) ---
    "analyze.history.reanalyze.action": "Re-analyze",
    "analyze.history.reanalyze.confirmTitle": "Re-analyze this upload?",
    "analyze.history.reanalyze.confirmDesc":
      "The {count} reviews in this upload will be re-analyzed with the new classification rules; human corrections are preserved. This may take a while.",
    "analyze.history.reanalyze.confirm": "Re-analyze",
    "analyze.history.reanalyze.cancel": "Cancel",
    "analyze.history.reanalyze.submitting": "Queueing…",
    "analyze.history.reanalyze.queued": "Re-analysis queued",
    "analyze.history.reanalyze.failed": "Could not start the re-analysis.",
    "analyze.history.reanalyze.noPermission":
      "Re-analysis requires a tenant admin role.",
    "analyze.history.reanalyze.allButton": "Re-analyze all reviews",
    "analyze.history.reanalyze.allConfirmTitle":
      "Re-analyze every review in this tenant?",
    "analyze.history.reanalyze.allConfirmDesc":
      "EVERY review in this tenant will be re-analyzed from scratch with the new classification rules; human corrections are preserved. Depending on your data volume this can take a long time, and analysis results will keep changing until it finishes. To update a single upload, use the per-row Re-analyze action instead.",
    "analyze.history.reanalyze.allConfirm": "Yes, re-analyze everything",

    // --- Column mapping (components/analyze/column-mapping-preview.tsx) ---
    "analyze.mapping.hint":
      'Click a column\'s description to change it manually. Columns set to "Ignore" are excluded from the upload.',
    "analyze.mapping.manuallyChanged": "manually changed",
    "analyze.mapping.autoDetectedInline": "(auto-detected)",
    "analyze.mapping.sampleLabel": "Sample: ",
    "analyze.mapping.alternativeLabel": "Alternative detection: ",
    "analyze.mapping.noRows": "No rows to preview.",

    // --- Confidence badge (components/analyze/confidence-badge.tsx) ---
    "analyze.confidence.high": "High confidence",
    "analyze.confidence.medium": "Medium confidence",
    "analyze.confidence.low": "Low confidence — please check",

    // --- PII warning (components/analyze/pii-warning-banner.tsx) ---
    "analyze.pii.heading":
      "This file contains column(s) that may include personal data.",
    "analyze.pii.detectedColumns": "Detected column(s): ",
    "analyze.pii.body":
      "Values in these columns will be processed during analysis and may be stored in the organization's data records. Under KVKK (data protection law), check the consent below to continue with the upload.",
    "analyze.pii.consent":
      "I consent to the processing of the personal data in these columns.",
  },
};
