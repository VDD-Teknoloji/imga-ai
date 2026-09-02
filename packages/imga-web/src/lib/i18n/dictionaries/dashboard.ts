import type { Bundle } from "./types";

/** dashboard alan sözlüğü (Sprint 12 i18n). */
export const dashboard: Bundle = {
  tr: {
    // --- ortak ---
    "dashboard.common.loading": "Yükleniyor…",
    "dashboard.common.loadFailed": "Veri yüklenemedi.",
    "dashboard.common.noData": "Veri yok.",
    "dashboard.common.all": "Tümü",
    "dashboard.common.view": "Görüntüle",
    "dashboard.common.quickActions": "Hızlı işlemler",
    "dashboard.common.top5Categories": "İlk 5 kategori",

    // --- ana sayfa ---
    "dashboard.home.noTenant": "Aktif kurum yok",
    "dashboard.home.greeting": "Merhaba",
    "dashboard.home.greetingNamed": "Merhaba, {name}",

    // --- veri kaynak şeridi (ana sayfa, Sprint 13.3) ---
    "dashboard.dataStrip.aria": "Veri özeti",
    "dashboard.dataStrip.total": "{n} yorum analiz edildi",
    "dashboard.dataStrip.sinceDate": "{date} tarihinden bu yana",
    "dashboard.dataStrip.range": "{from} – {to}",
    "dashboard.dataStrip.allTime": "Tüm dönem",
    "dashboard.dataStrip.unspecified": "Belirtilmemiş {n}",
    "dashboard.dataStrip.empty": "Henüz analiz edilmiş veri yok.",

    // --- strateji ---
    "dashboard.strategy.tab.swot": "SWOT Üret",
    "dashboard.strategy.tab.okr": "OKR Üret",
    "dashboard.strategy.tab.history": "Geçmiş",
    "dashboard.strategy.title": "Strateji",
    "dashboard.strategy.subtitle":
      "Analizleriniz üzerine SWOT ve OKR raporları üretin. Raporlar Gemini ile oluşturulur ve PDF olarak indirilebilir.",
    "dashboard.strategy.banner.title": "Strateji raporu üretmek için Gemini API anahtarı gerekli.",
    "dashboard.strategy.banner.desc":
      "En az bir aktif anahtar tanımlanana kadar SWOT/OKR üretimi devre dışı. Geçmiş raporlar görüntülenebilir ve indirilebilir.",
    "dashboard.strategy.banner.addKey": "Anahtar ekle",
    "dashboard.strategy.swot.cardTitle": "SWOT raporu üret",
    "dashboard.strategy.swot.cardDesc":
      "Seçilen tarih aralığındaki analizler özetlenir, Gemini SWOT (güçlü/zayıf yönler, fırsat/tehdit) ve stratejik öneri çıktısı üretir. Tarih boş bırakılırsa son 90 gün kullanılır.",
    "dashboard.strategy.field.startDate": "Başlangıç",
    "dashboard.strategy.field.endDate": "Bitiş",
    "dashboard.strategy.swot.skipCache": "Önbelleği atla (yeniden üret)",
    "dashboard.strategy.swot.batchScopeLabel": "Yükleme kapsamı (opsiyonel)",
    "dashboard.strategy.swot.batchScopeHelp":
      "Bir yükleme seçerseniz SWOT sadece o yüklemenin yorumlarını analiz eder; aksi halde tarih aralığı içindeki tüm yorumlar kullanılır.",
    "dashboard.strategy.swot.generate": "SWOT üret",
    "dashboard.strategy.noKeyHint":
      "Aktif Gemini anahtarı yok — yukarıdaki uyarıdan eklemeniz gerekir.",
    "dashboard.strategy.swot.ready": "SWOT raporu hazır.",
    "dashboard.strategy.geminiUnavailable": "Gemini şu an erişilemiyor: {detail}",
    "dashboard.strategy.swot.generateFailed": "SWOT raporu üretilemedi.",
    "dashboard.strategy.reportLoading": "Rapor yükleniyor…",
    "dashboard.strategy.reportLoadFailed": "Rapor yüklenemedi.",
    "dashboard.strategy.swot.strengths": "Güçlü Yönler",
    "dashboard.strategy.swot.weaknesses": "Zayıf Yönler",
    "dashboard.strategy.swot.opportunities": "Fırsatlar",
    "dashboard.strategy.swot.threats": "Tehditler",
    "dashboard.strategy.swot.reportTitle": "SWOT Raporu",
    "dashboard.strategy.swot.noItems": "Madde yok.",
    "dashboard.strategy.swot.evidence": "Kanıt: {text}",
    "dashboard.strategy.swot.recommendations": "Stratejik Öneriler",
    "dashboard.strategy.swot.priorityBadge": "öncelik: {value}",
    "dashboard.strategy.swot.impactBadge": "etki: {value}",
    "dashboard.strategy.okr.cardTitle": "OKR raporu üret",
    "dashboard.strategy.okr.cardDesc":
      "OKR'lar mevcut bir SWOT raporundan türetilir — önce bir SWOT seçin, ardından Gemini hedef-anahtar sonuç önerisi üretir.",
    "dashboard.strategy.okr.sourceSwot": "Kaynak SWOT",
    "dashboard.strategy.okr.swotListLoading": "SWOT listesi yükleniyor…",
    "dashboard.strategy.okr.needSwotFirst": "Önce bir SWOT raporu üretmeniz gerekir.",
    "dashboard.strategy.okr.selectSwot": "Bir SWOT seçin…",
    "dashboard.strategy.okr.generate": "OKR üret",
    "dashboard.strategy.okr.ready": "OKR raporu hazır.",
    "dashboard.strategy.okr.generateFailed": "OKR raporu üretilemedi.",
    "dashboard.strategy.allPeriod": "tüm dönem",
    "dashboard.strategy.okr.reportTitle": "OKR Raporu",
    "dashboard.strategy.okr.sourceSwotPrefix": " · Kaynak SWOT: ",
    "dashboard.strategy.okr.noObjectives": "Hedef yok.",
    "dashboard.strategy.okr.objective": "Hedef {n}",
    "dashboard.strategy.okr.rationale": "Gerekçe: {text}",
    "dashboard.strategy.okr.keyResults": "Anahtar Sonuçlar",
    "dashboard.strategy.okr.metric": "Metrik",
    "dashboard.strategy.okr.baseline": "Mevcut",
    "dashboard.strategy.okr.target": "Hedef",
    "dashboard.strategy.history.cardTitle": "Rapor geçmişi",
    "dashboard.strategy.history.type": "Tür",
    "dashboard.strategy.history.recordsCount": "{n} kayıt",
    "dashboard.strategy.history.loadFailed": "Geçmiş yüklenemedi.",
    "dashboard.strategy.history.empty": "Henüz rapor yok.",
    "dashboard.strategy.history.sourceSwot": "kaynak SWOT: {id}…",
    "dashboard.strategy.pager.prev": "Önceki",
    "dashboard.strategy.pager.next": "Sonraki",
    "dashboard.strategy.refresh": "Yenile",
    "dashboard.strategy.pdf.downloadFailed": "İndirilemedi: {status} {detail}",
    "dashboard.strategy.pdf.downloadStartFailed": "İndirme başlatılamadı.",
    "dashboard.strategy.extract.added": "{n} aksiyon eklendi.",
    "dashboard.strategy.extract.failed": "Aksiyon çıkarma başarısız.",
    "dashboard.strategy.extract.button": "Aksiyon olarak çıkar",

    // --- aksiyonlar ---
    "dashboard.actionItems.title": "Aksiyonlar",
    "dashboard.actionItems.subtitle":
      "Yönetici özeti ve SWOT raporlarından çıkarılan veya manuel eklenen takip görevleri.",
    "dashboard.actionItems.new": "Yeni aksiyon",
    "dashboard.actionItems.focus.aria": "Yüksek öncelikli açık aksiyonlar",
    "dashboard.actionItems.focus.today": "Bugün dikkat",
    "dashboard.actionItems.focus.count": "{n} yüksek öncelikli açık aksiyon",
    "dashboard.actionItems.focus.seeAll": "Tümünü gör",
    "dashboard.actionItems.filter.status": "Durum",
    "dashboard.actionItems.filter.priority": "Öncelik",
    "dashboard.actionItems.filter.showArchived": "Arşivi göster",
    "dashboard.actionItems.recordsCount": "{n} kayıt",
    "dashboard.actionItems.listFailed": "Liste yüklenemedi.",
    "dashboard.actionItems.empty": "Aksiyon yok.",
    "dashboard.actionItems.archived": "Arşivde",
    "dashboard.actionItems.sourceSwot": "kaynak: SWOT",
    "dashboard.actionItems.sourceBriefing": "kaynak: Yönetici Özeti",
    "dashboard.actionItems.hideHistory": "Geçmişi gizle",
    "dashboard.actionItems.history": "Geçmiş",
    "dashboard.actionItems.restored": "Geri alındı.",
    "dashboard.actionItems.restore": "Geri al",
    "dashboard.actionItems.archiveConfirm": "Aksiyon arşivlensin mi? (Geri alınabilir)",
    "dashboard.actionItems.archivedToast": "Arşivlendi.",
    "dashboard.actionItems.archive": "Arşivle",
    "dashboard.actionItems.event.created": "Oluşturuldu",
    "dashboard.actionItems.event.updated": "Güncellendi",
    "dashboard.actionItems.event.archived": "Arşivlendi",
    "dashboard.actionItems.event.unarchived": "Geri alındı",
    "dashboard.actionItems.event.statusChanged": "Durum değişti",
    "dashboard.actionItems.event.priorityChanged": "Öncelik değişti",
    "dashboard.actionItems.event.assigned": "Atandı",
    "dashboard.actionItems.event.unassigned": "Atama kaldırıldı",
    "dashboard.actionItems.event.commented": "Yorum eklendi",
    "dashboard.actionItems.audit.loading": "Geçmiş yükleniyor…",
    "dashboard.actionItems.audit.failed": "Geçmiş yüklenemedi.",
    "dashboard.actionItems.audit.empty": "Olay yok.",
    "dashboard.actionItems.create.required": "Başlık ve açıklama zorunlu.",
    "dashboard.actionItems.create.added": "Aksiyon eklendi.",
    "dashboard.actionItems.create.failed": "Eklenemedi.",
    "dashboard.actionItems.create.title": "Yeni Aksiyon",
    "dashboard.actionItems.create.fieldTitle": "Başlık",
    "dashboard.actionItems.create.fieldDescription": "Açıklama",
    "dashboard.actionItems.create.fieldPriority": "Öncelik",
    "dashboard.actionItems.create.cancel": "İptal",
    "dashboard.actionItems.create.submit": "Ekle",

    // --- stratejik öncelik (ana sayfa sağ ray, Sprint 13.3) ---
    // Not: anahtar kasıtlı olarak "dashboard." önekini taşımıyor —
    // brifte belirtilen ad aynen kullanıldı.
    "actionItems.priority.title": "Stratejik öncelik",
    "actionItems.priority.desc": "SWOT analizinden gelen, bu dönem için en öncelikli konu.",
    "actionItems.priority.cta": "Stratejiyi aç",

    // --- trend uyarıları ---
    "dashboard.trendAlerts.title": "Trend Uyarıları",
    "dashboard.trendAlerts.subtitle":
      "KPI sapması eşiklerini geçen değişimler. Manuel evaluate ile yeni uyarıları yenileyebilirsiniz.",
    "dashboard.trendAlerts.newAlerts": "{n} yeni uyarı.",
    "dashboard.trendAlerts.evalFailed": "Değerlendirme başarısız.",
    "dashboard.trendAlerts.evaluateNow": "Şimdi Değerlendir",
    "dashboard.trendAlerts.filter.status": "Durum",
    "dashboard.trendAlerts.status.active": "Aktif",
    "dashboard.trendAlerts.status.acknowledged": "Onaylanmış",
    "dashboard.trendAlerts.status.dismissed": "Atılmış",
    "dashboard.trendAlerts.status.all": "Tümü",
    "dashboard.trendAlerts.listFailed": "Liste yüklenemedi.",
    "dashboard.trendAlerts.empty": "Bu filtrelerle uyarı yok.",
    "dashboard.trendAlerts.acknowledge": "Onayla",
    "dashboard.trendAlerts.dismiss": "At",
    "dashboard.trendAlerts.acknowledged": "Onaylandı",
    "dashboard.trendAlerts.dismissed": "Atıldı",

    // --- yönetici hero ---
    "dashboard.executiveHero.headline.critical.prefix": "Müşterileriniz ",
    "dashboard.executiveHero.headline.critical.keyword": "memnun değil",
    "dashboard.executiveHero.headline.watch.prefix": "Müşterilerinizin bir kısmı ",
    "dashboard.executiveHero.headline.watch.keyword": "memnun değil",
    "dashboard.executiveHero.headline.healthy.prefix": "Müşterileriniz ",
    "dashboard.executiveHero.headline.healthy.keyword": "memnun",
    "dashboard.executiveHero.headline.balanced.prefix": "Müşteri memnuniyeti ",
    "dashboard.executiveHero.headline.balanced.keyword": "dengeli",
    "dashboard.executiveHero.empty.title": "Müşterilerinizin sesini dinlemeye başlayın",
    "dashboard.executiveHero.empty.desc":
      "İlk yorum dosyanızı yükleyin — dakikalar içinde memnuniyet durumunuz, ana sorunlarınız ve yönetici özetiniz hazır olsun.",
    "dashboard.executiveHero.empty.descPointUp":
      "Yukarıdaki kutuya ilk yorum dosyanızı bırakın — dakikalar içinde memnuniyet durumunuz ve ana sorunlarınız hazır olsun.",
    "dashboard.executiveHero.empty.noWriteAccess":
      "Veri yükleme yetkiniz yok — kurum yöneticinizden ilk yorum dosyasını yüklemesini isteyin.",
    "dashboard.executiveHero.empty.upload": "İlk dosyanızı yükleyin",
    "dashboard.executiveHero.aria": "Müşteri memnuniyet durumu",
    "dashboard.executiveHero.overallLabel": "Genel müşteri memnuniyeti",
    "dashboard.executiveHero.summary.prefix": "Toplam",
    "dashboard.executiveHero.summary.mid1": "yorumdan",
    "dashboard.executiveHero.summary.mid2": "tanesi olumlu,",
    "dashboard.executiveHero.summary.suffix": "tanesi olumsuz.",
    "dashboard.executiveHero.satisfaction": "memnuniyet",
    "dashboard.executiveHero.trend.flat": "Son 30 günde memnuniyet değişmedi",
    "dashboard.executiveHero.trend.up": "Son 30 günde memnuniyet +{points} puan arttı",
    "dashboard.executiveHero.trend.down": "Son 30 günde memnuniyet −{points} puan düştü",
    "dashboard.executiveHero.reviewReviews": "Müşteri yorumlarını incele",
    "dashboard.executiveHero.reviewNegative": "Olumsuz yorumları incele",
    "dashboard.executiveHero.createActionPlan": "Aksiyon planı oluştur",
    "dashboard.executiveHero.legend.positive": "Olumlu",
    "dashboard.executiveHero.legend.neutral": "Nötr",
    "dashboard.executiveHero.legend.negative": "Olumsuz",
    // WS5 (2026-08-18) — SatisfactionBar segmentleri tıklanabilir oldu;
    // role="img" yerine role="group" + her segmentin kendi aria-label'i.
    "dashboard.executiveHero.satisfactionBarAria":
      "Memnuniyet dağılımı — bir segmente tıklayarak ilgili yorumları görüntüleyin",
    "dashboard.executiveHero.legend.segmentAria": "{label}: %{pct} — görüntülemek için tıklayın",
    "dashboard.executiveHero.windowEmpty.title": "Seçilen dönemde yorum yok",
    "dashboard.executiveHero.windowEmpty.desc":
      "Dönem filtresini genişletin veya yeni yorum verisi yükleyin.",
    "dashboard.executiveHero.batchEmpty.title": "Seçilen yüklemede yorum yok",
    "dashboard.executiveHero.batchEmpty.desc":
      "Başka bir yükleme seçin veya yükleme filtresini temizleyin.",
    "dashboard.executiveHero.scoreInfo.aria": "Memnuniyet skoru nasıl hesaplanır?",
    "dashboard.executiveHero.scoreInfo.text":
      "Memnuniyet skoru, pozitif yorumların tüm yorumlara (pozitif + nötr + negatif) oranıdır ve seçili döneme göre hesaplanır. Trend rozeti son 30 günü önceki 30 günle karşılaştırır.",

    // --- dönem filtresi ---
    "dashboard.window.label": "Dönem",
    "dashboard.window.3m": "Son 3 Ay",
    "dashboard.window.6m": "Son 6 Ay",
    "dashboard.window.all": "Tüm Zamanlar",

    // --- filtre çubuğu ---
    "dashboard.filterBar.customRange": "Özel aralık",
    "dashboard.filterBar.dateFromAria": "Başlangıç tarihi",
    "dashboard.filterBar.dateToAria": "Bitiş tarihi",
    "dashboard.filterBar.batchLabel": "Yükleme",
    "dashboard.filterBar.batchChipRemove": "Yükleme filtresini kaldır",
    "dashboard.filterBar.clear": "Filtreleri temizle",

    // --- kategori bazlı duygu dağılımı ---
    // --- alt kategori kırılımı + kök neden (Sprint 13.1) ---
    "dashboard.rootCause.action": "Kök Neden Analizi",
    // F1 (2026-09-02) — title/generate/regenerate/close/empty/meta/
    // suggestedAction silindi: yalnız orphan root-cause-dialog.tsx
    // kullanıyordu (dosya silindi, sıfır importer doğrulandı).
    // affectedSurface/noCredentials/providerUnavailable/generateFailed
    // kalıyor — root-cause-cards.tsx da bu anahtarları kullanıyor.
    "dashboard.rootCause.affectedSurface": "Etkilenen temas noktası",
    "dashboard.rootCause.noCredentials":
      "LLM API anahtarı tanımlanmamış. Ayarlar > Entegrasyonlar üzerinden ekleyin.",
    "dashboard.rootCause.providerUnavailable":
      "LLM sağlayıcısına şu an ulaşılamıyor. Biraz sonra tekrar deneyin.",
    "dashboard.rootCause.generateFailed": "Kök neden analizi oluşturulamadı.",

    // --- sade kategori kartı (ana sayfa, Sprint 13.3) ---
    "dashboard.categorySimple.title": "Kategorilere göre memnuniyet",
    "dashboard.categorySimple.subtitle": "En çok olumsuz yorum alan konular üstte",
    "dashboard.categorySimple.negShare": "%{pct} olumsuz",
    "dashboard.categorySimple.reviews": "{n} yorum",
    "dashboard.categorySimple.showAll": "Tümünü gör",
    "dashboard.categorySimple.empty": "Bu dönemde kategori verisi yok.",
    // F3 — alt kategori genişletme (kategori kartı).
    "dashboard.categorySimple.expand": "Alt kategoriler",
    "dashboard.categorySimple.collapse": "Gizle",
    "dashboard.categorySimple.subEmpty": "Alt kategori verisi yok.",
    "dashboard.categorySimple.unmatched": "Alt kategori atanmamış",

    // --- kök neden kartları (ana sayfa, A2) ---
    "dashboard.rootCauseCards.aria": "Kök neden ve önerilen aksiyonlar",
    // Sprint 13.3 (2026-09-01) — ürün sahibi talimatıyla üzerine yazıldı:
    // eski değer "Neden? Ne yapmalısınız?" idi.
    "dashboard.rootCauseCards.title": "En yoğun 3 kategori",
    "dashboard.rootCauseCards.inference": "Çıkarım",
    "dashboard.rootCauseCards.suggestion": "Öneri",
    "dashboard.rootCauseCards.otherCausesTitle": "Diğer başlıca nedenler",
    "dashboard.rootCauseCards.generating": "Kök neden analizi hazırlanıyor…",
    "dashboard.rootCauseCards.generatingHint":
      "Yeni yüklenen veriler işleniyor; sonuç birkaç dakika içinde burada görünecek.",
    "dashboard.rootCauseCards.shareChip": "olumsuzların payı: %{pct} · {count} yorum",
    "dashboard.rootCauseCards.shareChipCountOnly": "{count} olumsuz yorum",
    "dashboard.rootCauseCards.otherCauses": "Diğer nedenler ({n})",
    "dashboard.rootCauseCards.searchQuote": "Yorumlarda ara",
    "dashboard.rootCauseCards.evidenceLink": "Kanıtı gör ({n} yorum)",
    "dashboard.rootCauseCards.lastAnalysis": "Son analiz: {time}",
    "dashboard.rootCauseCards.showDetails": "Detayları gör",
    "dashboard.rootCauseCards.hideDetails": "Detayları gizle",
    "dashboard.rootCauseCards.queued":
      "Analiz kuyruğa alındı — sıradaki yüklemeden sonra hazır olur.",
    "dashboard.rootCauseCards.generateNow": "Şimdi oluştur",
    "dashboard.rootCauseCards.emptyViewer":
      "Kök neden analizi henüz yok — bir yönetici oluşturabilir.",
    "dashboard.rootCauseCards.notEnoughData": "Kök neden analizi için yeterli veri yok.",
    "dashboard.rootCauseCards.empty.title": "Kök neden analizleri burada görünecek",
    "dashboard.rootCauseCards.empty.desc":
      "Yeterli olumsuz yorum birikince kategori bazlı analiz otomatik hazırlanır.",

    // --- veri kalitesi koçu (ana sayfa, A2 — ClassificationQualityChip'in yerini alır) ---
    "dashboard.dataQuality.aria": "Veri kalitesi koçu",
    "dashboard.dataQuality.good": "Veri kaliteniz iyi — kök neden analizleriniz güvenilir temelde.",
    "dashboard.dataQuality.flaggedShare":
      "Boş/anlamsız/kopya işaretli yorum oranı: %{pct} ({count} yorum)",
    "dashboard.dataQuality.hint": "Veri kalitesi arttıkça kök neden isabeti artar.",
    "dashboard.dataQuality.excluded":
      "Bu kayıtlar kök neden örneklemine hiç girmiyor; her temiz kayıt analiz isabetini artırır.",
    "dashboard.dataQuality.cta": "Temsilci dökümünü gör",
    "dashboard.dataQuality.questionCount": "Ayrıca müşterileriniz {n} soru sordu.",
    "dashboard.dataQuality.escalation":
      "{n} yorumda resmî şikâyet veya dava tehdidi var — önce bunlara bakın.",
    "dashboard.dataQuality.escalationCta": "Tehdit içeren yorumları gör",

    // --- aksayan süreçler (ana sayfa sağ ray, F1 2026-09-02) ---
    "dashboard.failingProcesses.title": "Aksayan süreçler",
    "dashboard.failingProcesses.trendAlerts": "{n} aktif trend uyarısı var",
    "dashboard.failingProcesses.slaResolution": "Çözüm SLA'sı %{pct} ihlal ediliyor",
    "dashboard.failingProcesses.slaFirstResponse": "İlk yanıt SLA'sı %{pct} ihlal ediliyor",
    "dashboard.failingProcesses.viral": "{n} olumsuz tweet yüksek etkileşim aldı",

    // --- sektör hatırlatması (ana sayfa sağ ray, F1 2026-09-02) ---
    "dashboard.contextNudge.text":
      "Sektörünüzü belirtin — kök neden önerileri kurumunuza göre özelleşir",

    // --- deneyim dağılımı kartları ---
    "dashboard.experience.title": "Deneyim Dağılımı",
    "dashboard.experience.infoAria": "Deneyim dağılımı nasıl hesaplanır?",
    "dashboard.experience.info":
      "Deneyim tipi her yorum için analiz sırasında belirlenir: dijital kanallardaki sorunlar (uygulama, site, online ödeme) dijital; fiziksel süreçler (kargo, iade, ürün, mağaza) operasyonel sayılır. Bu bilgiyi taşımayan eski yorumlar kategorilerine göre yaklaşık olarak yerleştirilir; hiçbirine giremeyenler yüzdelere dahil edilmez.",
    "dashboard.experience.digital": "Dijital Deneyim",
    "dashboard.experience.operational": "Operasyonel Deneyim",
    "dashboard.experience.reviews": "yorum",
    "dashboard.experience.negativeShare": "{count} olumsuz",
    "dashboard.experience.unassignedNote":
      "{count} yorum deneyim ataması bekliyor (yeniden analizle atanır)",
    "dashboard.experience.viewReviews": "Yorumları gör",
    // F2 (2026-09-01) — atanmamış deneyim notunun eylem butonu.
    "dashboard.experience.reanalyzeCta": "Yeniden analiz et",
    "dashboard.experience.reanalyzeConfirm":
      "Tüm yorumlar güncel modelle yeniden analiz edilsin mi? İnsan düzeltmeleri korunur.",
    "dashboard.experience.reanalyzeQueued": "Yeniden analiz kuyruğa alındı.",
    "dashboard.experience.reanalyzeFailed": "Yeniden analiz başlatılamadı.",
    "dashboard.experience.reanalyzeHistoryLink": "Geçmiş Yüklemeler",

    // --- önce yükleme (24 saat kuralı) ---
    "dashboard.uploadFirst.title": "Bugün henüz veri yüklemediniz",
    "dashboard.uploadFirst.desc":
      "Son 24 saatte yeni yorum verisi gelmedi. Analizlerin güncel kalması için son müşteri yorumlarınızı yükleyin — sonuçlar dakikalar içinde bu sayfaya yansır.",
    "dashboard.uploadFirst.titleNew": "Hoş geldiniz — ilk yorum dosyanızı yükleyelim",
    "dashboard.uploadFirst.descNew":
      "Henüz hiç yorum yüklemediniz. CSV veya Excel dosyanızı aşağıya bırakın; imga birkaç dakika içinde duygu, kategori ve kök neden analizini çıkarsın.",

    // --- öncelikli aksiyon ---

    // --- hızlı kapılar ---
    "dashboard.quickLinks.briefing.label": "Yönetici Özeti oluştur",
    "dashboard.quickLinks.briefing.desc": "Dönem raporu",
    "dashboard.quickLinks.strategy.label": "SWOT / OKR oluştur",
    "dashboard.quickLinks.strategy.desc": "Stratejik analiz",
    "dashboard.quickLinks.tickets.label": "Ticket'lar",
    "dashboard.quickLinks.tickets.desc": "Açık müşteri Ticket'ları",
    "dashboard.quickLinks.reports.label": "Rapor indir",
    "dashboard.quickLinks.reports.desc": "PDF / Excel dışa aktarım",

    // --- yükleme rıhtımı ---
    "dashboard.uploadDock.acceptError": "Sadece .csv veya .xlsx dosyaları kabul edilir.",
    "dashboard.uploadDock.sizeError": "Dosya 50 MB sınırını aşıyor.",
    "dashboard.uploadDock.uploadError": "Yükleme sırasında beklenmeyen bir hata oluştu.",
    "dashboard.uploadDock.aria": "Hızlı yükleme",
    "dashboard.uploadDock.title": "Hızlı yükleme",
    "dashboard.uploadDock.subtitle": "Dosyayı bırakın — analiz burada başlasın",
    "dashboard.uploadDock.uploading": "Dosya yükleniyor…",
    "dashboard.uploadDock.done.title": "Analiz tamamlandı",
    "dashboard.uploadDock.done.analyzed": "{n} yorum analiz edildi",
    "dashboard.uploadDock.done.failed": " · {n} satır hatalı",
    "dashboard.uploadDock.done.updated": ". Yukarıdaki rapor güncellendi.",
    "dashboard.uploadDock.seeResults": "Sonuçları gör",
    "dashboard.uploadDock.newUpload": "Yeni yükleme",
    "dashboard.uploadDock.retry": "Tekrar dene",
    "dashboard.uploadDock.advanced": "Gelişmiş yükleme",
    "dashboard.uploadDock.hint.prefix": "Şablon standardı: yorumlar ",
    "dashboard.uploadDock.hint.mid": " kolonunda. Farklı düzendeki dosyalar için ",
    "dashboard.uploadDock.hint.linkText": "gelişmiş yükleme",
    "dashboard.uploadDock.drop.title": "CSV / XLSX dosyanızı buraya bırakın",
    "dashboard.uploadDock.drop.subtitle": "veya tıklayarak seçin · en fazla 50 MB",
    "dashboard.uploadDock.dimensionNudge":
      "Tarih ve temsilci kolonlarınız da varsa gelişmiş yüklemeden eşleyin — trend ve veri kalitesi kartları daha isabetli çalışır.",

    // --- bugün dikkat listesi ---
    "dashboard.attentionList.empty":
      "Negatif sinyal yok — son dönemde dikkat çeken bir kategori bulunmadı.",
    "dashboard.attentionList.rowTotal": "toplam {n} yorum içinde",
    "dashboard.attentionList.rowNegative": "{n} negatif yorum",
    "dashboard.attentionList.title": "Bugün dikkat",
    "dashboard.attentionList.subtitle": "en çok negatif yorum alan kategoriler",

    // --- kategori dağılımı ---
    "dashboard.categoryChart.title": "Kategori dağılımı",

    // --- kategori × duygu ısı haritası ---
    "dashboard.categoryHeatmap.title": "Kategori × Duygu",
    "dashboard.categoryHeatmap.tooltip": "{row} × {col}: {value} analiz",

    // --- manşet metrik kartları ---
    "dashboard.headlineMetrics.band.noData": "Yeterli veri yok",
    "dashboard.headlineMetrics.band.excellent": "Mükemmel",
    "dashboard.headlineMetrics.band.good": "İyi",
    "dashboard.headlineMetrics.band.improvable": "Geliştirilebilir",
    "dashboard.headlineMetrics.band.risky": "Riskli",
    "dashboard.headlineMetrics.band.critical": "Kritik",
    "dashboard.headlineMetrics.npsAria": "NPS skoru",
    "dashboard.headlineMetrics.coverage": "kapsama %{pct}",
    "dashboard.headlineMetrics.totalReviews": "Toplam yorum",
    "dashboard.headlineMetrics.totalReviewsHint": "Aktif kayıt",
    "dashboard.headlineMetrics.openTickets": "Açık ticket",
    "dashboard.headlineMetrics.openTicketsHint": "Açık + ilerlemekte + bekleyen",
    "dashboard.headlineMetrics.openedToday": "Bugün açılan",
    "dashboard.headlineMetrics.openedTodayHint": "Bugünün başından beri",
    "dashboard.headlineMetrics.crisisCount": "Kriz adedi",
    "dashboard.headlineMetrics.crisisCountHint": "Çok negatif (≤ −0,80)",
    "dashboard.headlineMetrics.sensitiveTopics": "Hassas konular",
    "dashboard.headlineMetrics.sensitiveTopicsHint": "Tier-1 / Tier-2 tetikleyici",
    "dashboard.headlineMetrics.avgSentiment": "Ort. duygu",
    "dashboard.headlineMetrics.avgSentimentRange": "−1,0 ile +1,0 arası",

    // --- CX sağlık hero ---
    "dashboard.healthHero.band.noData": "Yeterli veri yok",
    "dashboard.healthHero.band.excellent": "Mükemmel",
    "dashboard.healthHero.band.good": "İyi",
    "dashboard.healthHero.band.watch": "Dikkat",
    "dashboard.healthHero.band.risk": "Riskli",
    "dashboard.healthHero.band.critical": "Kritik",
    "dashboard.healthHero.narrative.empty":
      "Henüz analiz edilmiş yorum yok. Toplu yükleme ile başlayın.",
    "dashboard.healthHero.narrative.crisis":
      "Kriz hacmi yüksek — son dönemde negatif sinyaller yoğunlaşıyor, dikkat gerekli.",
    "dashboard.healthHero.narrative.veryNegative":
      "Genel his belirgin biçimde negatif — yönetim aksiyonu değerlendirin.",
    "dashboard.healthHero.narrative.negative":
      "Genel his hafif negatif — eğilim tersine dönmeden ele alın.",
    "dashboard.healthHero.narrative.avgNegative": "Ortalama duygu negatif tarafa eğilimli.",
    "dashboard.healthHero.narrative.good": "Genel seyir iyi — kritik bir sinyal yok.",
    "dashboard.healthHero.narrative.balanced": "Genel seyir dengeli — periyodik takip yeterli.",
    "dashboard.healthHero.deltaLabel": "önceki aya göre {delta}",
    "dashboard.healthHero.error.title": "CX Sağlık verisi alınamadı.",
    "dashboard.healthHero.error.desc": "API erişimi yeniden kurulduğunda otomatik yenilenir.",
    "dashboard.healthHero.aria": "CX Sağlık",
    "dashboard.healthHero.headerLabel": "CX Sağlık · Son 30 gün",
    "dashboard.healthHero.coverage.totalReviews": "Toplam yorum",
    "dashboard.healthHero.coverage.npsCoverage": "NPS kapsama",
    "dashboard.healthHero.coverage.crisisCount": "Kriz adedi",
    "dashboard.healthHero.coverage.openTickets": "Açık ticket",

    // --- KPI hedef kartları ---
    "dashboard.kpiGoals.empty":
      "Henüz KPI hedefi yok. İlk hedefinizi ekleyerek dashboard kartlarında achievement yüzdesini görün.",
    "dashboard.kpiGoals.addGoal": "Hedef ekle",
    "dashboard.kpiGoals.title": "KPI Hedefleri",
    "dashboard.kpiGoals.edit": "Düzenle",
    "dashboard.kpiGoals.state.noData": "Veri yok",
    "dashboard.kpiGoals.state.onTrack": "Yolda",
    "dashboard.kpiGoals.state.atRisk": "Risk altında",
    "dashboard.kpiGoals.state.belowTarget": "Hedef altında",

    // --- metrik kartları (ticket) ---
    "dashboard.metricCards.openTickets": "Açık ticket",
    "dashboard.metricCards.openTicketsHint": "Açık, ilerlemekte veya müşteri bekleyen",
    "dashboard.metricCards.openedToday": "Bugün açılan",
    "dashboard.metricCards.openedTodayHint": "Bugünün başından beri yeni ticket",
    "dashboard.metricCards.highPriority": "Yüksek öncelik",
    "dashboard.metricCards.highPriorityHint": "Acil ya da yüksek, henüz kapatılmamış",
    "dashboard.metricCards.resolved7d": "Son 7 günde çözülen",
    "dashboard.metricCards.resolved7dHint": "Çözüldü veya kapatıldı",

    // --- NPS aylık trend ---
    "dashboard.npsMonthlyTrend.title": "Son 12 ay NPS trendi",
    "dashboard.npsMonthlyTrend.subtitle": "Aylık · veri olmayan aylar boşluk olarak görünür",
    "dashboard.npsMonthlyTrend.tooltipNoData": "veri yok",
    "dashboard.npsMonthlyTrend.months": "Oca,Şub,Mar,Nis,May,Haz,Tem,Ağu,Eyl,Eki,Kas,Ara",

    // --- hızlı işlem kutuları ---
    "dashboard.quickActions.newUpload": "Yeni yükleme",
    "dashboard.quickActions.newUploadHint": "CSV / Excel toplu analiz",
    "dashboard.quickActions.briefing": "Yönetici Özeti",
    "dashboard.quickActions.briefingHint": "Aylık yönetici özeti",
    "dashboard.quickActions.actionItemsLabel": "Aksiyonlar",
    "dashboard.quickActions.actionItemsOpen": "{n} açık aksiyon",
    "dashboard.quickActions.actionItemsNone": "Bekleyen yok",
    "dashboard.quickActions.strategy": "Strateji raporu",
    "dashboard.quickActions.strategyHint": "SWOT / OKR",
    "dashboard.quickActions.badgeAria": "{n} bekleyen",

    // --- son ticket'lar ---
    "dashboard.recentTickets.title": "Son ticket'lar",
    "dashboard.recentTickets.seeAll": "Tümünü gör",
    "dashboard.recentTickets.empty": "Henüz ticket yok.",
    "dashboard.recentTickets.colTitle": "Başlık",
    "dashboard.recentTickets.colCategory": "Kategori",
    "dashboard.recentTickets.colStatus": "Durum",
    "dashboard.recentTickets.colLastUpdate": "Son güncelleme",

    // --- duygu dağılımı donut ---
    "dashboard.sentimentDonut.title": "Duygu dağılımı",
    "dashboard.sentimentDonut.allTime": "Tüm zaman",

    // --- duygu trendi ---
    "dashboard.sentimentTrend.title": "Son 30 gün duygu trendi",
    "dashboard.sentimentTrend.daily": "Günlük bazda",
    "dashboard.sentimentTrend.negative": "Negatif",
    "dashboard.sentimentTrend.neutral": "Nötr",
    "dashboard.sentimentTrend.positive": "Pozitif",
  },
  en: {
    // --- common ---
    "dashboard.common.loading": "Loading…",
    "dashboard.common.loadFailed": "Couldn't load data.",
    "dashboard.common.noData": "No data.",
    "dashboard.common.all": "All",
    "dashboard.common.view": "View",
    "dashboard.common.quickActions": "Quick actions",
    "dashboard.common.top5Categories": "Top 5 categories",

    // --- home ---
    "dashboard.home.noTenant": "No active organization",
    "dashboard.home.greeting": "Hello",
    "dashboard.home.greetingNamed": "Hello, {name}",

    // --- data source strip (home page, Sprint 13.3) ---
    "dashboard.dataStrip.aria": "Data summary",
    "dashboard.dataStrip.total": "{n} reviews analysed",
    "dashboard.dataStrip.sinceDate": "since {date}",
    "dashboard.dataStrip.range": "{from} – {to}",
    "dashboard.dataStrip.allTime": "All time",
    "dashboard.dataStrip.unspecified": "Unspecified {n}",
    "dashboard.dataStrip.empty": "No analysed data yet.",

    // --- strategy ---
    "dashboard.strategy.tab.swot": "Generate SWOT",
    "dashboard.strategy.tab.okr": "Generate OKR",
    "dashboard.strategy.tab.history": "History",
    "dashboard.strategy.title": "Strategy",
    "dashboard.strategy.subtitle":
      "Generate SWOT and OKR reports from your analyses. Reports are created with Gemini and can be downloaded as PDF.",
    "dashboard.strategy.banner.title": "A Gemini API key is required to generate strategy reports.",
    "dashboard.strategy.banner.desc":
      "SWOT/OKR generation is disabled until at least one active key is defined. Past reports can still be viewed and downloaded.",
    "dashboard.strategy.banner.addKey": "Add key",
    "dashboard.strategy.swot.cardTitle": "Generate SWOT report",
    "dashboard.strategy.swot.cardDesc":
      "Analyses in the selected date range are summarized, and Gemini produces a SWOT (strengths/weaknesses, opportunities/threats) plus strategic recommendations. If dates are left blank, the last 90 days are used.",
    "dashboard.strategy.field.startDate": "Start",
    "dashboard.strategy.field.endDate": "End",
    "dashboard.strategy.swot.skipCache": "Skip cache (regenerate)",
    "dashboard.strategy.swot.batchScopeLabel": "Upload scope (optional)",
    "dashboard.strategy.swot.batchScopeHelp":
      "If you select an upload, the SWOT analyzes only that upload's reviews; otherwise all reviews within the date range are used.",
    "dashboard.strategy.swot.generate": "Generate SWOT",
    "dashboard.strategy.noKeyHint":
      "No active Gemini key — you need to add one from the notice above.",
    "dashboard.strategy.swot.ready": "SWOT report is ready.",
    "dashboard.strategy.geminiUnavailable": "Gemini is currently unavailable: {detail}",
    "dashboard.strategy.swot.generateFailed": "Couldn't generate the SWOT report.",
    "dashboard.strategy.reportLoading": "Loading report…",
    "dashboard.strategy.reportLoadFailed": "Couldn't load the report.",
    "dashboard.strategy.swot.strengths": "Strengths",
    "dashboard.strategy.swot.weaknesses": "Weaknesses",
    "dashboard.strategy.swot.opportunities": "Opportunities",
    "dashboard.strategy.swot.threats": "Threats",
    "dashboard.strategy.swot.reportTitle": "SWOT Report",
    "dashboard.strategy.swot.noItems": "No items.",
    "dashboard.strategy.swot.evidence": "Evidence: {text}",
    "dashboard.strategy.swot.recommendations": "Strategic Recommendations",
    "dashboard.strategy.swot.priorityBadge": "priority: {value}",
    "dashboard.strategy.swot.impactBadge": "impact: {value}",
    "dashboard.strategy.okr.cardTitle": "Generate OKR report",
    "dashboard.strategy.okr.cardDesc":
      "OKRs are derived from an existing SWOT report — select a SWOT first, then Gemini generates objective and key-result suggestions.",
    "dashboard.strategy.okr.sourceSwot": "Source SWOT",
    "dashboard.strategy.okr.swotListLoading": "Loading SWOT list…",
    "dashboard.strategy.okr.needSwotFirst": "You need to generate a SWOT report first.",
    "dashboard.strategy.okr.selectSwot": "Select a SWOT…",
    "dashboard.strategy.okr.generate": "Generate OKR",
    "dashboard.strategy.okr.ready": "OKR report is ready.",
    "dashboard.strategy.okr.generateFailed": "Couldn't generate the OKR report.",
    "dashboard.strategy.allPeriod": "all time",
    "dashboard.strategy.okr.reportTitle": "OKR Report",
    "dashboard.strategy.okr.sourceSwotPrefix": " · Source SWOT: ",
    "dashboard.strategy.okr.noObjectives": "No objectives.",
    "dashboard.strategy.okr.objective": "Objective {n}",
    "dashboard.strategy.okr.rationale": "Rationale: {text}",
    "dashboard.strategy.okr.keyResults": "Key Results",
    "dashboard.strategy.okr.metric": "Metric",
    "dashboard.strategy.okr.baseline": "Current",
    "dashboard.strategy.okr.target": "Target",
    "dashboard.strategy.history.cardTitle": "Report history",
    "dashboard.strategy.history.type": "Type",
    "dashboard.strategy.history.recordsCount": "{n} records",
    "dashboard.strategy.history.loadFailed": "Couldn't load history.",
    "dashboard.strategy.history.empty": "No reports yet.",
    "dashboard.strategy.history.sourceSwot": "source SWOT: {id}…",
    "dashboard.strategy.pager.prev": "Previous",
    "dashboard.strategy.pager.next": "Next",
    "dashboard.strategy.refresh": "Refresh",
    "dashboard.strategy.pdf.downloadFailed": "Couldn't download: {status} {detail}",
    "dashboard.strategy.pdf.downloadStartFailed": "Couldn't start the download.",
    "dashboard.strategy.extract.added": "{n} action items added.",
    "dashboard.strategy.extract.failed": "Couldn't extract action items.",
    "dashboard.strategy.extract.button": "Extract as action items",

    // --- action items ---
    "dashboard.actionItems.title": "Action Items",
    "dashboard.actionItems.subtitle":
      "Follow-up tasks extracted from the executive summary and SWOT reports, or added manually.",
    "dashboard.actionItems.new": "New action item",
    "dashboard.actionItems.focus.aria": "High-priority open action items",
    "dashboard.actionItems.focus.today": "Attention today",
    "dashboard.actionItems.focus.count": "{n} high-priority open action items",
    "dashboard.actionItems.focus.seeAll": "See all",
    "dashboard.actionItems.filter.status": "Status",
    "dashboard.actionItems.filter.priority": "Priority",
    "dashboard.actionItems.filter.showArchived": "Show archive",
    "dashboard.actionItems.recordsCount": "{n} records",
    "dashboard.actionItems.listFailed": "Couldn't load the list.",
    "dashboard.actionItems.empty": "No action items.",
    "dashboard.actionItems.archived": "Archived",
    "dashboard.actionItems.sourceSwot": "source: SWOT",
    "dashboard.actionItems.sourceBriefing": "source: Executive Summary",
    "dashboard.actionItems.hideHistory": "Hide history",
    "dashboard.actionItems.history": "History",
    "dashboard.actionItems.restored": "Restored.",
    "dashboard.actionItems.restore": "Restore",
    "dashboard.actionItems.archiveConfirm": "Archive this action item? (Can be undone)",
    "dashboard.actionItems.archivedToast": "Archived.",
    "dashboard.actionItems.archive": "Archive",
    "dashboard.actionItems.event.created": "Created",
    "dashboard.actionItems.event.updated": "Updated",
    "dashboard.actionItems.event.archived": "Archived",
    "dashboard.actionItems.event.unarchived": "Restored",
    "dashboard.actionItems.event.statusChanged": "Status changed",
    "dashboard.actionItems.event.priorityChanged": "Priority changed",
    "dashboard.actionItems.event.assigned": "Assigned",
    "dashboard.actionItems.event.unassigned": "Unassigned",
    "dashboard.actionItems.event.commented": "Comment added",
    "dashboard.actionItems.audit.loading": "Loading history…",
    "dashboard.actionItems.audit.failed": "Couldn't load history.",
    "dashboard.actionItems.audit.empty": "No events.",
    "dashboard.actionItems.create.required": "Title and description are required.",
    "dashboard.actionItems.create.added": "Action item added.",
    "dashboard.actionItems.create.failed": "Couldn't add.",
    "dashboard.actionItems.create.title": "New Action Item",
    "dashboard.actionItems.create.fieldTitle": "Title",
    "dashboard.actionItems.create.fieldDescription": "Description",
    "dashboard.actionItems.create.fieldPriority": "Priority",
    "dashboard.actionItems.create.cancel": "Cancel",
    "dashboard.actionItems.create.submit": "Add",

    // --- strategic priority (home page right rail, Sprint 13.3) ---
    // Note: key intentionally has no "dashboard." prefix — kept as
    // named in the shared brief.
    "actionItems.priority.title": "Strategic priority",
    "actionItems.priority.desc":
      "The highest-priority topic for this period, from your SWOT analysis.",
    "actionItems.priority.cta": "Open strategy",

    // --- trend alerts ---
    "dashboard.trendAlerts.title": "Trend Alerts",
    "dashboard.trendAlerts.subtitle":
      "Changes that exceed KPI deviation thresholds. Use manual evaluation to refresh new alerts.",
    "dashboard.trendAlerts.newAlerts": "{n} new alerts.",
    "dashboard.trendAlerts.evalFailed": "Evaluation failed.",
    "dashboard.trendAlerts.evaluateNow": "Evaluate Now",
    "dashboard.trendAlerts.filter.status": "Status",
    "dashboard.trendAlerts.status.active": "Active",
    "dashboard.trendAlerts.status.acknowledged": "Acknowledged",
    "dashboard.trendAlerts.status.dismissed": "Dismissed",
    "dashboard.trendAlerts.status.all": "All",
    "dashboard.trendAlerts.listFailed": "Couldn't load the list.",
    "dashboard.trendAlerts.empty": "No alerts for these filters.",
    "dashboard.trendAlerts.acknowledge": "Acknowledge",
    "dashboard.trendAlerts.dismiss": "Dismiss",
    "dashboard.trendAlerts.acknowledged": "Acknowledged",
    "dashboard.trendAlerts.dismissed": "Dismissed",

    // --- executive hero ---
    "dashboard.executiveHero.headline.critical.prefix": "Your customers are ",
    "dashboard.executiveHero.headline.critical.keyword": "not satisfied",
    "dashboard.executiveHero.headline.watch.prefix": "Some of your customers are ",
    "dashboard.executiveHero.headline.watch.keyword": "not satisfied",
    "dashboard.executiveHero.headline.healthy.prefix": "Your customers are ",
    "dashboard.executiveHero.headline.healthy.keyword": "satisfied",
    "dashboard.executiveHero.headline.balanced.prefix": "Customer satisfaction is ",
    "dashboard.executiveHero.headline.balanced.keyword": "balanced",
    "dashboard.executiveHero.empty.title": "Start listening to your customers' voice",
    "dashboard.executiveHero.empty.desc":
      "Upload your first review file — within minutes your satisfaction status, main problems, and executive summary will be ready.",
    "dashboard.executiveHero.empty.descPointUp":
      "Drop your first review file in the box above — within minutes your satisfaction status and main problems will be ready.",
    "dashboard.executiveHero.empty.noWriteAccess":
      "You don't have upload access — ask your organization admin to upload the first review file.",
    "dashboard.executiveHero.empty.upload": "Upload your first file",
    "dashboard.executiveHero.aria": "Customer satisfaction status",
    "dashboard.executiveHero.overallLabel": "Overall customer satisfaction",
    "dashboard.executiveHero.summary.prefix": "Of",
    "dashboard.executiveHero.summary.mid1": "total reviews,",
    "dashboard.executiveHero.summary.mid2": "are positive and",
    "dashboard.executiveHero.summary.suffix": "are negative.",
    "dashboard.executiveHero.satisfaction": "satisfaction",
    "dashboard.executiveHero.trend.flat": "Satisfaction unchanged in the last 30 days",
    "dashboard.executiveHero.trend.up": "Satisfaction rose {points} points in the last 30 days",
    "dashboard.executiveHero.trend.down": "Satisfaction fell {points} points in the last 30 days",
    "dashboard.executiveHero.reviewReviews": "Review customer feedback",
    "dashboard.executiveHero.reviewNegative": "Review negative feedback",
    "dashboard.executiveHero.createActionPlan": "Create an action plan",
    "dashboard.executiveHero.legend.positive": "Positive",
    "dashboard.executiveHero.legend.neutral": "Neutral",
    "dashboard.executiveHero.legend.negative": "Negative",
    // WS5 (2026-08-18) — SatisfactionBar segments became clickable;
    // role="img" replaced with role="group" + a per-segment aria-label.
    "dashboard.executiveHero.satisfactionBarAria":
      "Satisfaction distribution — click a segment to view the matching reviews",
    "dashboard.executiveHero.legend.segmentAria": "{label}: {pct}% — click to view",
    "dashboard.executiveHero.windowEmpty.title": "No reviews in the selected period",
    "dashboard.executiveHero.windowEmpty.desc":
      "Widen the period filter or upload new review data.",
    "dashboard.executiveHero.batchEmpty.title": "No reviews in the selected upload",
    "dashboard.executiveHero.batchEmpty.desc": "Pick another upload or clear the upload filter.",
    "dashboard.executiveHero.scoreInfo.aria": "How is the satisfaction score calculated?",
    "dashboard.executiveHero.scoreInfo.text":
      "The satisfaction score is the share of positive reviews among all reviews (positive + neutral + negative), calculated for the selected period. The trend badge compares the last 30 days with the previous 30 days.",

    // --- period filter ---
    "dashboard.window.label": "Period",
    "dashboard.window.3m": "Last 3 Months",
    "dashboard.window.6m": "Last 6 Months",
    "dashboard.window.all": "All Time",

    // --- filter bar ---
    "dashboard.filterBar.customRange": "Custom range",
    "dashboard.filterBar.dateFromAria": "Start date",
    "dashboard.filterBar.dateToAria": "End date",
    "dashboard.filterBar.batchLabel": "Upload",
    "dashboard.filterBar.batchChipRemove": "Remove upload filter",
    "dashboard.filterBar.clear": "Clear filters",

    // --- category sentiment breakdown ---
    // --- sub-category drill-down + root cause (Sprint 13.1) ---
    "dashboard.rootCause.action": "Root Cause Analysis",
    // F1 (2026-09-02) — title/generate/regenerate/close/empty/meta/
    // suggestedAction removed: only the orphaned root-cause-dialog.tsx
    // used them (file deleted, zero importers confirmed).
    "dashboard.rootCause.affectedSurface": "Affected touchpoint",
    "dashboard.rootCause.noCredentials":
      "No LLM API key configured. Add one under Settings > Integrations.",
    "dashboard.rootCause.providerUnavailable":
      "The LLM provider is unavailable right now. Please try again shortly.",
    "dashboard.rootCause.generateFailed": "Could not generate the root cause analysis.",

    // --- simple category card (home page, Sprint 13.3) ---
    "dashboard.categorySimple.title": "Satisfaction by category",
    "dashboard.categorySimple.subtitle": "Topics with the most negative reviews first",
    "dashboard.categorySimple.negShare": "{pct}% negative",
    "dashboard.categorySimple.reviews": "{n} reviews",
    "dashboard.categorySimple.showAll": "See all",
    "dashboard.categorySimple.empty": "No category data in this period.",
    // F3 — sub-category expand (category card).
    "dashboard.categorySimple.expand": "Sub-categories",
    "dashboard.categorySimple.collapse": "Hide",
    "dashboard.categorySimple.subEmpty": "No sub-category data.",
    "dashboard.categorySimple.unmatched": "No sub-category assigned",

    // --- root cause cards (home page, A2) ---
    "dashboard.rootCauseCards.aria": "Root causes and suggested actions",
    // Sprint 13.3 (2026-09-01) — overwritten per product-owner
    // instruction: old value was "Why? What should you do?".
    "dashboard.rootCauseCards.title": "Top 3 categories",
    "dashboard.rootCauseCards.inference": "Insight",
    "dashboard.rootCauseCards.suggestion": "Suggestion",
    "dashboard.rootCauseCards.otherCausesTitle": "Other main causes",
    "dashboard.rootCauseCards.generating": "Preparing the root-cause analysis…",
    "dashboard.rootCauseCards.generatingHint":
      "The newly uploaded data is being processed; the result will appear here in a few minutes.",
    "dashboard.rootCauseCards.shareChip": "share of negatives: {pct}% · {count} reviews",
    "dashboard.rootCauseCards.shareChipCountOnly": "{count} negative reviews",
    "dashboard.rootCauseCards.otherCauses": "Other causes ({n})",
    "dashboard.rootCauseCards.searchQuote": "Search in reviews",
    "dashboard.rootCauseCards.evidenceLink": "See the evidence ({n} reviews)",
    "dashboard.rootCauseCards.lastAnalysis": "Last analysis: {time}",
    "dashboard.rootCauseCards.showDetails": "Show details",
    "dashboard.rootCauseCards.hideDetails": "Hide details",
    "dashboard.rootCauseCards.queued": "Analysis is queued — ready after the next upload.",
    "dashboard.rootCauseCards.generateNow": "Generate now",
    "dashboard.rootCauseCards.emptyViewer":
      "No root cause analysis yet — a manager can generate one.",
    "dashboard.rootCauseCards.notEnoughData": "Not enough data for a root cause analysis.",
    "dashboard.rootCauseCards.empty.title": "Root cause analyses will appear here",
    "dashboard.rootCauseCards.empty.desc":
      "Once enough negative reviews build up, analysis is prepared automatically.",

    // --- data quality coach (home page, A2 — replaces ClassificationQualityChip) ---
    "dashboard.dataQuality.aria": "Data quality coach",
    "dashboard.dataQuality.good":
      "Your data quality is good — your root cause analyses rest on a reliable foundation.",
    "dashboard.dataQuality.flaggedShare":
      "Share of reviews flagged empty/meaningless/duplicate: {pct}% ({count} reviews)",
    "dashboard.dataQuality.hint": "Better data quality means sharper root causes.",
    "dashboard.dataQuality.excluded":
      "These records never enter the root-cause sample; every clean record sharpens the analysis.",
    "dashboard.dataQuality.cta": "See the per-agent breakdown",
    "dashboard.dataQuality.questionCount": "Also, your customers asked {n} questions.",
    "dashboard.dataQuality.escalation":
      "{n} reviews threaten a formal complaint or legal action — start with these.",
    "dashboard.dataQuality.escalationCta": "See the reviews with threats",

    // --- failing processes (home right rail, F1 2026-09-02) ---
    "dashboard.failingProcesses.title": "Processes at risk",
    "dashboard.failingProcesses.trendAlerts": "{n} active trend alerts",
    "dashboard.failingProcesses.slaResolution": "Resolution SLA violated at {pct}%",
    "dashboard.failingProcesses.slaFirstResponse": "First response SLA violated at {pct}%",
    "dashboard.failingProcesses.viral": "{n} negative tweets got high engagement",

    // --- context nudge (home right rail, F1 2026-09-02) ---
    "dashboard.contextNudge.text":
      "Tell us your industry — root cause suggestions get tailored to your business",

    // --- experience breakdown cards ---
    "dashboard.experience.title": "Experience Breakdown",
    "dashboard.experience.infoAria": "How is the experience breakdown calculated?",
    "dashboard.experience.info":
      "The experience type is decided per review during analysis: problems in digital channels (app, website, online payment) count as digital; physical processes (shipping, returns, product, store) count as operational. Older reviews without this information are placed approximately by their category; reviews that fit neither are excluded from the percentages.",
    "dashboard.experience.digital": "Digital Experience",
    "dashboard.experience.operational": "Operational Experience",
    "dashboard.experience.reviews": "reviews",
    "dashboard.experience.negativeShare": "{count} negative",
    "dashboard.experience.unassignedNote":
      "{count} reviews are awaiting an experience assignment (a re-analysis assigns them)",
    "dashboard.experience.viewReviews": "View reviews",
    // F2 (2026-09-01) — action button on the unassigned-experience note.
    "dashboard.experience.reanalyzeCta": "Re-analyse",
    "dashboard.experience.reanalyzeConfirm":
      "Re-analyse all reviews with the current model? Human corrections are preserved.",
    "dashboard.experience.reanalyzeQueued": "Re-analysis queued.",
    "dashboard.experience.reanalyzeFailed": "Couldn't start the re-analysis.",
    "dashboard.experience.reanalyzeHistoryLink": "Past uploads",

    // --- upload first (24-hour rule) ---
    "dashboard.uploadFirst.title": "You haven't uploaded data today",
    "dashboard.uploadFirst.desc":
      "No new review data has arrived in the last 24 hours. Upload your latest customer reviews to keep the analyses fresh — results land on this page within minutes.",
    "dashboard.uploadFirst.titleNew": "Welcome — let's upload your first review file",
    "dashboard.uploadFirst.descNew":
      "You haven't uploaded any reviews yet. Drop your CSV or Excel file below; imga will extract sentiment, category, and root-cause analysis within minutes.",

    // --- priority action ---

    // --- quick links ---
    "dashboard.quickLinks.briefing.label": "Create Executive Summary",
    "dashboard.quickLinks.briefing.desc": "Period report",
    "dashboard.quickLinks.strategy.label": "Create SWOT / OKR",
    "dashboard.quickLinks.strategy.desc": "Strategic analysis",
    "dashboard.quickLinks.tickets.label": "Tickets",
    "dashboard.quickLinks.tickets.desc": "Open customer Tickets",
    "dashboard.quickLinks.reports.label": "Download report",
    "dashboard.quickLinks.reports.desc": "PDF / Excel export",

    // --- upload dock ---
    "dashboard.uploadDock.acceptError": "Only .csv or .xlsx files are accepted.",
    "dashboard.uploadDock.sizeError": "File exceeds the 50 MB limit.",
    "dashboard.uploadDock.uploadError": "An unexpected error occurred during upload.",
    "dashboard.uploadDock.aria": "Quick upload",
    "dashboard.uploadDock.title": "Quick upload",
    "dashboard.uploadDock.subtitle": "Drop a file — analysis starts right here",
    "dashboard.uploadDock.uploading": "Uploading file…",
    "dashboard.uploadDock.done.title": "Analysis complete",
    "dashboard.uploadDock.done.analyzed": "{n} reviews analyzed",
    "dashboard.uploadDock.done.failed": " · {n} rows failed",
    "dashboard.uploadDock.done.updated": ". The report above has been updated.",
    "dashboard.uploadDock.seeResults": "See results",
    "dashboard.uploadDock.newUpload": "New upload",
    "dashboard.uploadDock.retry": "Try again",
    "dashboard.uploadDock.advanced": "Advanced upload",
    "dashboard.uploadDock.hint.prefix": "Template standard: reviews go in the ",
    "dashboard.uploadDock.hint.mid": " column. For files with a different layout, use ",
    "dashboard.uploadDock.hint.linkText": "advanced upload",
    "dashboard.uploadDock.drop.title": "Drop your CSV / XLSX file here",
    "dashboard.uploadDock.drop.subtitle": "or click to choose · up to 50 MB",
    "dashboard.uploadDock.dimensionNudge":
      "If you also have date and agent columns, map them via advanced upload — trend and data-quality cards work more precisely.",

    // --- attention list ---
    "dashboard.attentionList.empty": "No negative signals — no category stood out recently.",
    "dashboard.attentionList.rowTotal": "within {n} total reviews",
    "dashboard.attentionList.rowNegative": "{n} negative reviews",
    "dashboard.attentionList.title": "Attention today",
    "dashboard.attentionList.subtitle": "categories with the most negative reviews",

    // --- category distribution ---
    "dashboard.categoryChart.title": "Category distribution",

    // --- category × sentiment heatmap ---
    "dashboard.categoryHeatmap.title": "Category × Sentiment",
    "dashboard.categoryHeatmap.tooltip": "{row} × {col}: {value} analyses",

    // --- headline metric cards ---
    "dashboard.headlineMetrics.band.noData": "Not enough data",
    "dashboard.headlineMetrics.band.excellent": "Excellent",
    "dashboard.headlineMetrics.band.good": "Good",
    "dashboard.headlineMetrics.band.improvable": "Needs improvement",
    "dashboard.headlineMetrics.band.risky": "At risk",
    "dashboard.headlineMetrics.band.critical": "Critical",
    "dashboard.headlineMetrics.npsAria": "NPS score",
    "dashboard.headlineMetrics.coverage": "{pct}% coverage",
    "dashboard.headlineMetrics.totalReviews": "Total reviews",
    "dashboard.headlineMetrics.totalReviewsHint": "Active records",
    "dashboard.headlineMetrics.openTickets": "Open tickets",
    "dashboard.headlineMetrics.openTicketsHint": "Open + in progress + pending",
    "dashboard.headlineMetrics.openedToday": "Opened today",
    "dashboard.headlineMetrics.openedTodayHint": "Since the start of today",
    "dashboard.headlineMetrics.crisisCount": "Crisis count",
    "dashboard.headlineMetrics.crisisCountHint": "Very negative (≤ −0.80)",
    "dashboard.headlineMetrics.sensitiveTopics": "Sensitive topics",
    "dashboard.headlineMetrics.sensitiveTopicsHint": "Tier-1 / Tier-2 trigger",
    "dashboard.headlineMetrics.avgSentiment": "Avg. sentiment",
    "dashboard.headlineMetrics.avgSentimentRange": "Between −1.0 and +1.0",

    // --- CX health hero ---
    "dashboard.healthHero.band.noData": "Not enough data",
    "dashboard.healthHero.band.excellent": "Excellent",
    "dashboard.healthHero.band.good": "Good",
    "dashboard.healthHero.band.watch": "Watch",
    "dashboard.healthHero.band.risk": "At risk",
    "dashboard.healthHero.band.critical": "Critical",
    "dashboard.healthHero.narrative.empty": "No analyzed reviews yet. Start with a batch upload.",
    "dashboard.healthHero.narrative.crisis":
      "Crisis volume is high — negative signals have intensified recently, attention needed.",
    "dashboard.healthHero.narrative.veryNegative":
      "Overall sentiment is clearly negative — consider management action.",
    "dashboard.healthHero.narrative.negative":
      "Overall sentiment is slightly negative — address it before the trend reverses.",
    "dashboard.healthHero.narrative.avgNegative": "Average sentiment leans negative.",
    "dashboard.healthHero.narrative.good": "The overall trend is good — no critical signals.",
    "dashboard.healthHero.narrative.balanced":
      "The overall trend is balanced — periodic monitoring is enough.",
    "dashboard.healthHero.deltaLabel": "{delta} vs. previous month",
    "dashboard.healthHero.error.title": "Couldn't load CX Health data.",
    "dashboard.healthHero.error.desc": "It refreshes automatically once API access is restored.",
    "dashboard.healthHero.aria": "CX Health",
    "dashboard.healthHero.headerLabel": "CX Health · Last 30 days",
    "dashboard.healthHero.coverage.totalReviews": "Total reviews",
    "dashboard.healthHero.coverage.npsCoverage": "NPS coverage",
    "dashboard.healthHero.coverage.crisisCount": "Crisis count",
    "dashboard.healthHero.coverage.openTickets": "Open tickets",

    // --- KPI goal cards ---
    "dashboard.kpiGoals.empty":
      "No KPI goals yet. Add your first goal to see the achievement percentage on dashboard cards.",
    "dashboard.kpiGoals.addGoal": "Add goal",
    "dashboard.kpiGoals.title": "KPI Goals",
    "dashboard.kpiGoals.edit": "Edit",
    "dashboard.kpiGoals.state.noData": "No data",
    "dashboard.kpiGoals.state.onTrack": "On track",
    "dashboard.kpiGoals.state.atRisk": "At risk",
    "dashboard.kpiGoals.state.belowTarget": "Below target",

    // --- metric cards (ticket) ---
    "dashboard.metricCards.openTickets": "Open tickets",
    "dashboard.metricCards.openTicketsHint": "Open, in progress, or pending customer",
    "dashboard.metricCards.openedToday": "Opened today",
    "dashboard.metricCards.openedTodayHint": "New tickets since the start of today",
    "dashboard.metricCards.highPriority": "High priority",
    "dashboard.metricCards.highPriorityHint": "Urgent or high, not yet closed",
    "dashboard.metricCards.resolved7d": "Resolved in last 7 days",
    "dashboard.metricCards.resolved7dHint": "Resolved or closed",

    // --- NPS monthly trend ---
    "dashboard.npsMonthlyTrend.title": "Last 12 months NPS trend",
    "dashboard.npsMonthlyTrend.subtitle": "Monthly · months with no data appear as gaps",
    "dashboard.npsMonthlyTrend.tooltipNoData": "no data",
    "dashboard.npsMonthlyTrend.months": "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec",

    // --- quick action tiles ---
    "dashboard.quickActions.newUpload": "New upload",
    "dashboard.quickActions.newUploadHint": "CSV / Excel batch analysis",
    "dashboard.quickActions.briefing": "Executive Summary",
    "dashboard.quickActions.briefingHint": "Monthly executive summary",
    "dashboard.quickActions.actionItemsLabel": "Action Items",
    "dashboard.quickActions.actionItemsOpen": "{n} open action items",
    "dashboard.quickActions.actionItemsNone": "None pending",
    "dashboard.quickActions.strategy": "Strategy report",
    "dashboard.quickActions.strategyHint": "SWOT / OKR",
    "dashboard.quickActions.badgeAria": "{n} pending",

    // --- recent tickets ---
    "dashboard.recentTickets.title": "Recent tickets",
    "dashboard.recentTickets.seeAll": "See all",
    "dashboard.recentTickets.empty": "No tickets yet.",
    "dashboard.recentTickets.colTitle": "Title",
    "dashboard.recentTickets.colCategory": "Category",
    "dashboard.recentTickets.colStatus": "Status",
    "dashboard.recentTickets.colLastUpdate": "Last update",

    // --- sentiment donut ---
    "dashboard.sentimentDonut.title": "Sentiment distribution",
    "dashboard.sentimentDonut.allTime": "All time",

    // --- sentiment trend ---
    "dashboard.sentimentTrend.title": "Last 30 days sentiment trend",
    "dashboard.sentimentTrend.daily": "Daily",
    "dashboard.sentimentTrend.negative": "Negative",
    "dashboard.sentimentTrend.neutral": "Neutral",
    "dashboard.sentimentTrend.positive": "Positive",
  },
};
