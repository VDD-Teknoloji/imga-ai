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

    // --- strateji ---
    "dashboard.strategy.tab.swot": "SWOT Üret",
    "dashboard.strategy.tab.okr": "OKR Üret",
    "dashboard.strategy.tab.history": "Geçmiş",
    "dashboard.strategy.title": "Strateji",
    "dashboard.strategy.subtitle":
      "Analizleriniz üzerine SWOT ve OKR raporları üretin. Raporlar Gemini ile oluşturulur ve PDF olarak indirilebilir.",
    "dashboard.strategy.banner.title":
      "Strateji raporu üretmek için Gemini API anahtarı gerekli.",
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
    "dashboard.strategy.okr.needSwotFirst":
      "Önce bir SWOT raporu üretmeniz gerekir.",
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
    "dashboard.actionItems.archiveConfirm":
      "Aksiyon arşivlensin mi? (Geri alınabilir)",
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

    // --- yönetici özeti şeridi ---
    "dashboard.aiInsight.period.week": "Haftalık",
    "dashboard.aiInsight.period.month": "Aylık",
    "dashboard.aiInsight.period.quarter": "Üç aylık",
    "dashboard.aiInsight.empty.title": "Yönetici özetinizi oluşturun",
    "dashboard.aiInsight.empty.desc":
      "Dönemin değişimleri, kritik içgörüler ve öncelikli aksiyonlar — tek tıkla.",
    "dashboard.aiInsight.aria": "Yönetici özeti",
    "dashboard.aiInsight.label": "Yönetici Özeti",
    "dashboard.aiInsight.seeFull": "Özetin tamamını gör",

    // --- yönetici hero ---
    "dashboard.executiveHero.headline.critical.prefix": "Müşterileriniz ",
    "dashboard.executiveHero.headline.critical.keyword": "memnun değil",
    "dashboard.executiveHero.headline.watch.prefix":
      "Müşterilerinizin bir kısmı ",
    "dashboard.executiveHero.headline.watch.keyword": "memnun değil",
    "dashboard.executiveHero.headline.healthy.prefix": "Müşterileriniz ",
    "dashboard.executiveHero.headline.healthy.keyword": "memnun",
    "dashboard.executiveHero.headline.balanced.prefix": "Müşteri memnuniyeti ",
    "dashboard.executiveHero.headline.balanced.keyword": "dengeli",
    "dashboard.executiveHero.empty.title":
      "Müşterilerinizin sesini dinlemeye başlayın",
    "dashboard.executiveHero.empty.desc":
      "İlk yorum dosyanızı yükleyin — dakikalar içinde memnuniyet durumunuz, ana sorunlarınız ve yönetici özetiniz hazır olsun.",
    "dashboard.executiveHero.empty.upload": "İlk dosyanızı yükleyin",
    "dashboard.executiveHero.aria": "Müşteri memnuniyet durumu",
    "dashboard.executiveHero.overallLabel": "Genel müşteri memnuniyeti",
    "dashboard.executiveHero.summary.prefix": "Toplam",
    "dashboard.executiveHero.summary.mid1": "yorumdan",
    "dashboard.executiveHero.summary.mid2": "tanesi olumlu,",
    "dashboard.executiveHero.summary.suffix": "tanesi olumsuz.",
    "dashboard.executiveHero.satisfaction": "memnuniyet",
    "dashboard.executiveHero.trend.flat": "Son 30 günde memnuniyet değişmedi",
    "dashboard.executiveHero.trend.up":
      "Son 30 günde memnuniyet +{points} puan arttı",
    "dashboard.executiveHero.trend.down":
      "Son 30 günde memnuniyet −{points} puan düştü",
    "dashboard.executiveHero.reviewReviews": "Müşteri yorumlarını incele",
    "dashboard.executiveHero.reviewNegative": "Olumsuz yorumları incele",
    "dashboard.executiveHero.createActionPlan": "Aksiyon planı oluştur",
    "dashboard.executiveHero.legend.positive": "Olumlu",
    "dashboard.executiveHero.legend.neutral": "Nötr",
    "dashboard.executiveHero.legend.negative": "Olumsuz",
    "dashboard.executiveHero.windowEmpty.title": "Seçilen dönemde yorum yok",
    "dashboard.executiveHero.windowEmpty.desc":
      "Dönem filtresini genişletin veya yeni yorum verisi yükleyin.",
    "dashboard.executiveHero.scoreInfo.aria":
      "Memnuniyet skoru nasıl hesaplanır?",
    "dashboard.executiveHero.scoreInfo.text":
      "Memnuniyet skoru, pozitif yorumların tüm yorumlara (pozitif + nötr + negatif) oranıdır ve seçili döneme göre hesaplanır. Trend rozeti son 30 günü önceki 30 günle karşılaştırır.",
    "dashboard.executiveHero.swotCta": "SWOT Analizi",

    // --- dönem filtresi ---
    "dashboard.window.label": "Dönem",
    "dashboard.window.3m": "Son 3 Ay",
    "dashboard.window.6m": "Son 6 Ay",
    "dashboard.window.all": "Tüm Zamanlar",

    // --- NPS dağılımı kartı ---
    "dashboard.npsCard.title": "NPS Dağılımı",
    "dashboard.npsCard.infoAria": "NPS nasıl hesaplanır?",
    "dashboard.npsCard.info":
      "NPS = Destekçi yüzdesi − Kötüleyen yüzdesi (−100 ile +100 arası). 0-10 ölçeğinde 9-10 puan Destekçi, 7-8 Pasif, 0-6 Kötüleyen sayılır.",
    "dashboard.npsCard.promoters": "Destekçiler",
    "dashboard.npsCard.passives": "Pasifler",
    "dashboard.npsCard.detractors": "Kötüleyenler",
    "dashboard.npsCard.scoreLabel": "NPS Skoru",
    "dashboard.npsCard.empty":
      "Bu dönemde NPS verisi yok. Yükleme dosyanızda NPS kolonu eşlerseniz dağılım burada görünür.",
    "dashboard.npsCard.coverage": "NPS verisi olan yorum oranı: %{pct}",

    // --- kategori bazlı duygu dağılımı ---
    "dashboard.categoryBreakdown.title": "Kategori Bazlı Duygu Dağılımı",
    "dashboard.categoryBreakdown.subtitle":
      "En sorunlu kategori en üstte — her kategorideki olumsuz / nötr / olumlu payı. Bir dilime tıklayınca ilgili yorumlar açılır.",
    "dashboard.categoryBreakdown.empty": "Bu dönemde kategori verisi yok.",
    "dashboard.categoryBreakdown.rowTotal": "Toplam {n} yorum",

    // --- deneyim dağılımı kartları ---
    "dashboard.experience.title": "Deneyim Dağılımı",
    "dashboard.experience.infoAria": "Deneyim dağılımı nasıl hesaplanır?",
    "dashboard.experience.info":
      "Yorumlar kategorilerine göre iki deneyim tipine ayrılır: Teknik Destek ve Faturalama/Ödeme dijital; kargo, iade, ürün kalitesi gibi kategoriler operasyonel sayılır. Sınıflandırılamayan yorumlar dahil edilmez.",
    "dashboard.experience.digital": "Dijital Deneyim",
    "dashboard.experience.operational": "Operasyonel Deneyim",
    "dashboard.experience.reviews": "yorum",
    "dashboard.experience.viewReviews": "Yorumları gör",

    // --- önce yükleme (24 saat kuralı) ---
    "dashboard.uploadFirst.title": "Bugün henüz veri yüklemediniz",
    "dashboard.uploadFirst.desc":
      "Son 24 saatte yeni yorum verisi gelmedi. Analizlerin güncel kalması için son müşteri yorumlarınızı yükleyin — sonuçlar dakikalar içinde bu sayfaya yansır.",

    // --- öncelikli aksiyon ---
    "dashboard.priorityAction.label": "Bu ayki önceliğiniz",
    "dashboard.priorityAction.seeFull": "Aksiyon planının tamamını gör",

    // --- en çok şikayet edilen konular ---
    "dashboard.topProblems.title": "En çok şikayet edilen konular",
    "dashboard.topProblems.description":
      "Müşterileriniz en çok bunlardan şikayetçi",
    "dashboard.topProblems.actionLabel": "Aksiyon planı",
    "dashboard.topProblems.statSuffix":
      "olumsuz yorum · şikayetlerin %{share}'i",

    // --- müşterinin sesi ---
    "dashboard.voiceOfCustomer.aria": "Müşterinin sesi",
    "dashboard.voiceOfCustomer.title": "Müşterinin Sesi",
    "dashboard.voiceOfCustomer.description": "Yorumların kendi cümleleriyle",
    "dashboard.voiceOfCustomer.action": "Tüm yorumlar",
    "dashboard.voiceOfCustomer.sentiment.negative": "Olumsuz",
    "dashboard.voiceOfCustomer.sentiment.positive": "Olumlu",
    "dashboard.voiceOfCustomer.sentiment.neutral": "Nötr",

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
    "dashboard.uploadDock.acceptError":
      "Sadece .csv veya .xlsx dosyaları kabul edilir.",
    "dashboard.uploadDock.sizeError": "Dosya 50 MB sınırını aşıyor.",
    "dashboard.uploadDock.uploadError":
      "Yükleme sırasında beklenmeyen bir hata oluştu.",
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
    "dashboard.uploadDock.hint.mid":
      " kolonunda. Farklı düzendeki dosyalar için ",
    "dashboard.uploadDock.hint.linkText": "gelişmiş yükleme",
    "dashboard.uploadDock.drop.title": "CSV / XLSX dosyanızı buraya bırakın",
    "dashboard.uploadDock.drop.subtitle": "veya tıklayarak seçin · en fazla 50 MB",

    // --- strateji anlık kartları ---
    "dashboard.strategySnapshots.swot.emptyTitle": "SWOT analizinizi oluşturun",
    "dashboard.strategySnapshots.swot.emptyDesc":
      "Tüm yorumlarınız okunur; güçlü ve zayıf yönleriniz kanıtlarıyla çıkar.",
    "dashboard.strategySnapshots.swot.emptyCta": "SWOT oluştur",
    "dashboard.strategySnapshots.swot.title": "Son SWOT Analizi",
    "dashboard.strategySnapshots.swot.strengths": "Güçlü yönler",
    "dashboard.strategySnapshots.swot.weaknesses": "Zayıf yönler",
    "dashboard.strategySnapshots.swot.seeFull": "Analizin tamamı",
    "dashboard.strategySnapshots.okr.emptyTitle": "OKR hedeflerinizi oluşturun",
    "dashboard.strategySnapshots.okr.emptyDesc":
      "SWOT'unuzdan yola çıkarak önümüzdeki dönem için ölçülebilir hedefler üretilir.",
    "dashboard.strategySnapshots.okr.emptyCta": "OKR oluştur",
    "dashboard.strategySnapshots.okr.title": "Son OKR Hedefleri",
    "dashboard.strategySnapshots.okr.seeFull": "Hedeflerin tamamı",

    // --- sınıflandırma kalitesi ---
    "dashboard.classificationQuality.band.good": "İyi",
    "dashboard.classificationQuality.band.watch": "İyileştirilebilir",
    "dashboard.classificationQuality.band.low": "Düşük",
    "dashboard.classificationQuality.good.headline":
      "Sınıflandırma kalitesi: %{pct} eşleşme",
    "dashboard.classificationQuality.good.hint":
      "Yorumların çoğu doğru kategoriye düştü.",
    "dashboard.classificationQuality.uncertain.headline":
      "{count} yorum 'belirsiz' (%{pct})",
    "dashboard.classificationQuality.watch.hint":
      "Çok kısa veya bağlamsız yorumlar genellikle 'belirsiz'e düşer. Özel kategori eklemek oranı iyileştirir.",
    "dashboard.classificationQuality.low.hint":
      "Belirsiz oranı yüksek. Ayarlar / Kategoriler menüsünden özel kategoriler ekleyerek {total} yorumun daha büyük kısmını doğru sınıflandırabilirsiniz.",
    "dashboard.classificationQuality.aria": "Sınıflandırma kalite uyarısı",

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
    "dashboard.healthHero.narrative.avgNegative":
      "Ortalama duygu negatif tarafa eğilimli.",
    "dashboard.healthHero.narrative.good":
      "Genel seyir iyi — kritik bir sinyal yok.",
    "dashboard.healthHero.narrative.balanced":
      "Genel seyir dengeli — periyodik takip yeterli.",
    "dashboard.healthHero.deltaLabel": "önceki aya göre {delta}",
    "dashboard.healthHero.error.title": "CX Sağlık verisi alınamadı.",
    "dashboard.healthHero.error.desc":
      "API erişimi yeniden kurulduğunda otomatik yenilenir.",
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
    "dashboard.metricCards.openTicketsHint":
      "Açık, ilerlemekte veya müşteri bekleyen",
    "dashboard.metricCards.openedToday": "Bugün açılan",
    "dashboard.metricCards.openedTodayHint": "Bugünün başından beri yeni ticket",
    "dashboard.metricCards.highPriority": "Yüksek öncelik",
    "dashboard.metricCards.highPriorityHint":
      "Acil ya da yüksek, henüz kapatılmamış",
    "dashboard.metricCards.resolved7d": "Son 7 günde çözülen",
    "dashboard.metricCards.resolved7dHint": "Çözüldü veya kapatıldı",

    // --- NPS aylık trend ---
    "dashboard.npsMonthlyTrend.title": "Son 12 ay NPS trendi",
    "dashboard.npsMonthlyTrend.subtitle":
      "Aylık · veri olmayan aylar boşluk olarak görünür",
    "dashboard.npsMonthlyTrend.tooltipNoData": "veri yok",
    "dashboard.npsMonthlyTrend.months":
      "Oca,Şub,Mar,Nis,May,Haz,Tem,Ağu,Eyl,Eki,Kas,Ara",

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

    // --- strategy ---
    "dashboard.strategy.tab.swot": "Generate SWOT",
    "dashboard.strategy.tab.okr": "Generate OKR",
    "dashboard.strategy.tab.history": "History",
    "dashboard.strategy.title": "Strategy",
    "dashboard.strategy.subtitle":
      "Generate SWOT and OKR reports from your analyses. Reports are created with Gemini and can be downloaded as PDF.",
    "dashboard.strategy.banner.title":
      "A Gemini API key is required to generate strategy reports.",
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
    "dashboard.strategy.geminiUnavailable":
      "Gemini is currently unavailable: {detail}",
    "dashboard.strategy.swot.generateFailed":
      "Couldn't generate the SWOT report.",
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
    "dashboard.strategy.okr.needSwotFirst":
      "You need to generate a SWOT report first.",
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
    "dashboard.actionItems.archiveConfirm":
      "Archive this action item? (Can be undone)",
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
    "dashboard.actionItems.create.required":
      "Title and description are required.",
    "dashboard.actionItems.create.added": "Action item added.",
    "dashboard.actionItems.create.failed": "Couldn't add.",
    "dashboard.actionItems.create.title": "New Action Item",
    "dashboard.actionItems.create.fieldTitle": "Title",
    "dashboard.actionItems.create.fieldDescription": "Description",
    "dashboard.actionItems.create.fieldPriority": "Priority",
    "dashboard.actionItems.create.cancel": "Cancel",
    "dashboard.actionItems.create.submit": "Add",

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

    // --- executive summary strip ---
    "dashboard.aiInsight.period.week": "Weekly",
    "dashboard.aiInsight.period.month": "Monthly",
    "dashboard.aiInsight.period.quarter": "Quarterly",
    "dashboard.aiInsight.empty.title": "Create your executive summary",
    "dashboard.aiInsight.empty.desc":
      "Period changes, critical insights, and priority actions — in one click.",
    "dashboard.aiInsight.aria": "Executive summary",
    "dashboard.aiInsight.label": "Executive Summary",
    "dashboard.aiInsight.seeFull": "See the full summary",

    // --- executive hero ---
    "dashboard.executiveHero.headline.critical.prefix": "Your customers are ",
    "dashboard.executiveHero.headline.critical.keyword": "not satisfied",
    "dashboard.executiveHero.headline.watch.prefix":
      "Some of your customers are ",
    "dashboard.executiveHero.headline.watch.keyword": "not satisfied",
    "dashboard.executiveHero.headline.healthy.prefix": "Your customers are ",
    "dashboard.executiveHero.headline.healthy.keyword": "satisfied",
    "dashboard.executiveHero.headline.balanced.prefix":
      "Customer satisfaction is ",
    "dashboard.executiveHero.headline.balanced.keyword": "balanced",
    "dashboard.executiveHero.empty.title":
      "Start listening to your customers' voice",
    "dashboard.executiveHero.empty.desc":
      "Upload your first review file — within minutes your satisfaction status, main problems, and executive summary will be ready.",
    "dashboard.executiveHero.empty.upload": "Upload your first file",
    "dashboard.executiveHero.aria": "Customer satisfaction status",
    "dashboard.executiveHero.overallLabel": "Overall customer satisfaction",
    "dashboard.executiveHero.summary.prefix": "Of",
    "dashboard.executiveHero.summary.mid1": "total reviews,",
    "dashboard.executiveHero.summary.mid2": "are positive and",
    "dashboard.executiveHero.summary.suffix": "are negative.",
    "dashboard.executiveHero.satisfaction": "satisfaction",
    "dashboard.executiveHero.trend.flat":
      "Satisfaction unchanged in the last 30 days",
    "dashboard.executiveHero.trend.up":
      "Satisfaction rose {points} points in the last 30 days",
    "dashboard.executiveHero.trend.down":
      "Satisfaction fell {points} points in the last 30 days",
    "dashboard.executiveHero.reviewReviews": "Review customer feedback",
    "dashboard.executiveHero.reviewNegative": "Review negative feedback",
    "dashboard.executiveHero.createActionPlan": "Create an action plan",
    "dashboard.executiveHero.legend.positive": "Positive",
    "dashboard.executiveHero.legend.neutral": "Neutral",
    "dashboard.executiveHero.legend.negative": "Negative",
    "dashboard.executiveHero.windowEmpty.title":
      "No reviews in the selected period",
    "dashboard.executiveHero.windowEmpty.desc":
      "Widen the period filter or upload new review data.",
    "dashboard.executiveHero.scoreInfo.aria":
      "How is the satisfaction score calculated?",
    "dashboard.executiveHero.scoreInfo.text":
      "The satisfaction score is the share of positive reviews among all reviews (positive + neutral + negative), calculated for the selected period. The trend badge compares the last 30 days with the previous 30 days.",
    "dashboard.executiveHero.swotCta": "SWOT Analysis",

    // --- period filter ---
    "dashboard.window.label": "Period",
    "dashboard.window.3m": "Last 3 Months",
    "dashboard.window.6m": "Last 6 Months",
    "dashboard.window.all": "All Time",

    // --- NPS breakdown card ---
    "dashboard.npsCard.title": "NPS Distribution",
    "dashboard.npsCard.infoAria": "How is NPS calculated?",
    "dashboard.npsCard.info":
      "NPS = % Promoters − % Detractors (ranges from −100 to +100). On a 0-10 scale, 9-10 counts as Promoter, 7-8 as Passive and 0-6 as Detractor.",
    "dashboard.npsCard.promoters": "Promoters",
    "dashboard.npsCard.passives": "Passives",
    "dashboard.npsCard.detractors": "Detractors",
    "dashboard.npsCard.scoreLabel": "NPS Score",
    "dashboard.npsCard.empty":
      "No NPS data in this period. Map an NPS column in your upload file and the distribution will appear here.",
    "dashboard.npsCard.coverage": "Reviews carrying NPS data: {pct}%",

    // --- category sentiment breakdown ---
    "dashboard.categoryBreakdown.title": "Sentiment by Category",
    "dashboard.categoryBreakdown.subtitle":
      "Most problematic category first — negative / neutral / positive share per category. Click a slice to open the matching reviews.",
    "dashboard.categoryBreakdown.empty": "No category data in this period.",
    "dashboard.categoryBreakdown.rowTotal": "{n} reviews in total",

    // --- experience breakdown cards ---
    "dashboard.experience.title": "Experience Breakdown",
    "dashboard.experience.infoAria": "How is the experience breakdown calculated?",
    "dashboard.experience.info":
      "Reviews are split into two experience types by category: Technical Support and Billing/Payment count as digital; categories like shipping, returns and product quality count as operational. Unclassified reviews are excluded.",
    "dashboard.experience.digital": "Digital Experience",
    "dashboard.experience.operational": "Operational Experience",
    "dashboard.experience.reviews": "reviews",
    "dashboard.experience.viewReviews": "View reviews",

    // --- upload first (24-hour rule) ---
    "dashboard.uploadFirst.title": "You haven't uploaded data today",
    "dashboard.uploadFirst.desc":
      "No new review data has arrived in the last 24 hours. Upload your latest customer reviews to keep the analyses fresh — results land on this page within minutes.",

    // --- priority action ---
    "dashboard.priorityAction.label": "This month's priority",
    "dashboard.priorityAction.seeFull": "See the full action plan",

    // --- top problems ---
    "dashboard.topProblems.title": "Most-complained-about topics",
    "dashboard.topProblems.description":
      "What your customers complain about most",
    "dashboard.topProblems.actionLabel": "Action plan",
    "dashboard.topProblems.statSuffix":
      "negative reviews · {share}% of complaints",

    // --- voice of customer ---
    "dashboard.voiceOfCustomer.aria": "Voice of the customer",
    "dashboard.voiceOfCustomer.title": "Voice of the Customer",
    "dashboard.voiceOfCustomer.description": "In your customers' own words",
    "dashboard.voiceOfCustomer.action": "All reviews",
    "dashboard.voiceOfCustomer.sentiment.negative": "Negative",
    "dashboard.voiceOfCustomer.sentiment.positive": "Positive",
    "dashboard.voiceOfCustomer.sentiment.neutral": "Neutral",

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
    "dashboard.uploadDock.acceptError":
      "Only .csv or .xlsx files are accepted.",
    "dashboard.uploadDock.sizeError": "File exceeds the 50 MB limit.",
    "dashboard.uploadDock.uploadError":
      "An unexpected error occurred during upload.",
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
    "dashboard.uploadDock.hint.mid":
      " column. For files with a different layout, use ",
    "dashboard.uploadDock.hint.linkText": "advanced upload",
    "dashboard.uploadDock.drop.title": "Drop your CSV / XLSX file here",
    "dashboard.uploadDock.drop.subtitle": "or click to choose · up to 50 MB",

    // --- strategy snapshot cards ---
    "dashboard.strategySnapshots.swot.emptyTitle": "Create your SWOT analysis",
    "dashboard.strategySnapshots.swot.emptyDesc":
      "All your reviews are read; your strengths and weaknesses emerge with evidence.",
    "dashboard.strategySnapshots.swot.emptyCta": "Create SWOT",
    "dashboard.strategySnapshots.swot.title": "Latest SWOT Analysis",
    "dashboard.strategySnapshots.swot.strengths": "Strengths",
    "dashboard.strategySnapshots.swot.weaknesses": "Weaknesses",
    "dashboard.strategySnapshots.swot.seeFull": "Full analysis",
    "dashboard.strategySnapshots.okr.emptyTitle": "Create your OKR goals",
    "dashboard.strategySnapshots.okr.emptyDesc":
      "Measurable goals for the coming period are generated from your SWOT.",
    "dashboard.strategySnapshots.okr.emptyCta": "Create OKR",
    "dashboard.strategySnapshots.okr.title": "Latest OKR Goals",
    "dashboard.strategySnapshots.okr.seeFull": "All goals",

    // --- classification quality ---
    "dashboard.classificationQuality.band.good": "Good",
    "dashboard.classificationQuality.band.watch": "Can be improved",
    "dashboard.classificationQuality.band.low": "Low",
    "dashboard.classificationQuality.good.headline":
      "Classification quality: {pct}% match",
    "dashboard.classificationQuality.good.hint":
      "Most reviews landed in the correct category.",
    "dashboard.classificationQuality.uncertain.headline":
      "{count} reviews are 'uncertain' ({pct}%)",
    "dashboard.classificationQuality.watch.hint":
      "Very short or context-free reviews usually fall into 'uncertain'. Adding a custom category improves the rate.",
    "dashboard.classificationQuality.low.hint":
      "The uncertain rate is high. By adding custom categories from the Settings / Categories menu, you can correctly classify a larger portion of {total} reviews.",
    "dashboard.classificationQuality.aria": "Classification quality warning",

    // --- attention list ---
    "dashboard.attentionList.empty":
      "No negative signals — no category stood out recently.",
    "dashboard.attentionList.rowTotal": "within {n} total reviews",
    "dashboard.attentionList.rowNegative": "{n} negative reviews",
    "dashboard.attentionList.title": "Attention today",
    "dashboard.attentionList.subtitle":
      "categories with the most negative reviews",

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
    "dashboard.headlineMetrics.openTicketsHint":
      "Open + in progress + pending",
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
    "dashboard.healthHero.narrative.empty":
      "No analyzed reviews yet. Start with a batch upload.",
    "dashboard.healthHero.narrative.crisis":
      "Crisis volume is high — negative signals have intensified recently, attention needed.",
    "dashboard.healthHero.narrative.veryNegative":
      "Overall sentiment is clearly negative — consider management action.",
    "dashboard.healthHero.narrative.negative":
      "Overall sentiment is slightly negative — address it before the trend reverses.",
    "dashboard.healthHero.narrative.avgNegative":
      "Average sentiment leans negative.",
    "dashboard.healthHero.narrative.good":
      "The overall trend is good — no critical signals.",
    "dashboard.healthHero.narrative.balanced":
      "The overall trend is balanced — periodic monitoring is enough.",
    "dashboard.healthHero.deltaLabel": "{delta} vs. previous month",
    "dashboard.healthHero.error.title": "Couldn't load CX Health data.",
    "dashboard.healthHero.error.desc":
      "It refreshes automatically once API access is restored.",
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
    "dashboard.metricCards.openTicketsHint":
      "Open, in progress, or pending customer",
    "dashboard.metricCards.openedToday": "Opened today",
    "dashboard.metricCards.openedTodayHint":
      "New tickets since the start of today",
    "dashboard.metricCards.highPriority": "High priority",
    "dashboard.metricCards.highPriorityHint":
      "Urgent or high, not yet closed",
    "dashboard.metricCards.resolved7d": "Resolved in last 7 days",
    "dashboard.metricCards.resolved7dHint": "Resolved or closed",

    // --- NPS monthly trend ---
    "dashboard.npsMonthlyTrend.title": "Last 12 months NPS trend",
    "dashboard.npsMonthlyTrend.subtitle":
      "Monthly · months with no data appear as gaps",
    "dashboard.npsMonthlyTrend.tooltipNoData": "no data",
    "dashboard.npsMonthlyTrend.months":
      "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec",

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
