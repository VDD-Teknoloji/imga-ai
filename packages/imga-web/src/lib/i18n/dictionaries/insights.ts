import type { Bundle } from "./types";

/**
 * insights alan sözlüğü (Sprint 12 i18n).
 *
 * Kapsam: /insights (+ _components: cohort / heatmap / word-cloud tab'ları),
 * /reviews (liste + detay), /reports ve paylaşılan charts/heatmap. Anahtar
 * ön-ekleri sayfa/özellik alanına göredir (insights.* / reviews.* / reports.*
 * / charts.*); hepsi tek bir düz haritaya birleşir. Ortak "Yükleniyor…",
 * "İptal" gibi metinler core.ts'teki common.* anahtarlarını yeniden kullanır.
 */
export const insights: Bundle = {
  tr: {
    // --- /insights: sekmeler ---
    "insights.tabs.sentiment": "Duygu",
    "insights.tabs.category": "Kategori",
    "insights.tabs.nps": "NPS",
    "insights.tabs.cross": "Çapraz",
    "insights.tabs.perspective": "Perspektif",
    "insights.tabs.tickets": "Ticket",
    "insights.tabs.heatmap": "Isı haritası",
    "insights.tabs.cohort": "Kohort",
    "insights.tabs.wordcloud": "Kelimeler",
    "insights.tabs.overrides": "Kural Katmanları",
    // 2026-08-20 — Boyutlar sekmesi (iş boyutu breakdown'ı).
    "insights.tabs.dimensions": "Boyutlar",
    // 2026-08-21 — Operasyon sekmesi (SLA/CSAT/efor/tazmin/teslimat).
    "insights.tabs.operations": "Operasyon",

    // --- /insights: sayfa başlığı ---
    "insights.page.title": "İçgörüler",
    "insights.page.subtitle":
      "Duygu, kategori ve Ticket metriklerinin ayrıntılı görünümü.",

    // --- /insights: filtre çubuğu ---
    "insights.filter.allTime": "Tüm zamanlar",
    "insights.filter.noFilterHint":
      "Filtre uygulanmadı — başlangıç ve bitiş seçerek daraltın.",
    "insights.filter.startDate": "Başlangıç",
    "insights.filter.endDate": "Bitiş",
    "insights.filter.source": "Kaynak",
    "insights.filter.sourceAll": "Tümü",
    "insights.filter.sourceManualOnly": "Sadece Manuel",
    "insights.filter.sourceBatchOnly": "Sadece Toplu",

    // --- 2026-08-18 (Dalga 3, WS2): veri kalitesi include_flagged toggle ---
    // Paylaşılan bileşen (/insights + ana sayfa filtre çubuğu).
    "insights.filter.includeFlaggedLabel": "Düşük kaliteli veriyi dahil et",
    "insights.filter.includeFlaggedAria": "Düşük kaliteli veriyi dahil et",
    "insights.filter.includeFlaggedBadge":
      "tekrar/boş/bilgilendirme satırları dahil",

    // --- /insights: ortak durum metinleri ---
    "insights.state.loadError": "Veri yüklenemedi: {message}",
    "insights.state.loadErrorShort": "Veri yüklenemedi.",
    "insights.state.noData": "Bu filtrelerle veri bulunamadı.",
    "insights.state.noValue": "veri yok",

    // --- /insights: grafik başlıkları / notlar ---
    "insights.chart.sentimentDistribution": "Duygu Dağılımı",
    "insights.chart.scoreHistogram": "Skor Histogramı",
    "insights.chart.sentimentTrendDaily": "Duygu Trendi (gün)",
    "insights.chart.categoryTop10": "Kategori Top 10",
    "insights.chart.categorySentimentMatrix": "Kategori × Duygu Matrisi",
    "insights.chart.matrixTooltip": "{row} × {col}: {value} analiz",
    "insights.chart.belirsizNote":
      "\"Belirsiz\" kategori sınıflandırılamayan yorumları kapsar — büyük rakam genelde aşırı geniş veya çok kısa yorumlardan kaynaklanır. Tablonun sonuna alındı ki sinyalleri görmek kolaylaşsın.",
    "insights.chart.ruleLayers": "Kural Katmanları",
    "insights.chart.ruleLayersNotePre":
      "Kural katman sayımı Sprint 8.3.4'te doldurulacak (",
    "insights.chart.ruleLayersNotePost":
      "JSONB kolonu); şimdilik 5 katman sıfır sayımla gösteriliyor.",
    "insights.chart.npsScore": "NPS Skoru",
    "insights.chart.npsResponsesCoverage": "{count} yanıt · kapsama %{coverage}",
    "insights.chart.bucketDistribution": "Bucket Dağılımı",
    "insights.chart.monthlyTrend12": "Aylık Trend (son 12 ay)",
    "insights.chart.companyPerspectiveTop10": "Şirket Perspektifi Top 10",
    "insights.chart.unmatchedLabel": "Eşleşme yok:",
    "insights.chart.analysesCount": "{count} analiz",
    "insights.chart.unmatchedHint":
      "(heuristik bir taksonomi girdisiyle eşleşmedi).",
    "insights.chart.resolutionTimeDistribution": "Çözüm Süresi Dağılımı",
    "insights.chart.avg": "Ortalama",
    "insights.chart.median": "Ortanca",
    "insights.chart.hours": "{value} saat",

    // --- /insights: kohort tab ---
    "insights.cohort.periodWeek": "Hafta",
    "insights.cohort.periodMonth": "Ay",
    "insights.cohort.periodQuarter": "Çeyrek",
    "insights.cohort.dimTaxonomy": "Kategori",
    "insights.cohort.dimPerspective": "Şirket Perspektifi",
    "insights.cohort.dimNpsBucket": "NPS Kovası",
    "insights.cohort.period": "Dönem",
    "insights.cohort.dimension": "Boyut",
    "insights.cohort.topCohorts": "Top kohort",
    "insights.cohort.trendTitle": "Kohort Trendi",

    // --- /insights: boyutlar tab (2026-08-20) ---
    "insights.dimTab.dimension": "Boyut",
    "insights.dimTab.metric": "Metrik",
    "insights.dimTab.metricVolume": "Yorum Sayısı",
    "insights.dimTab.metricNegativeShare": "Olumsuz Payı %",
    "insights.dimTab.metricAvgScore": "Ortalama Skor",
    "insights.dimTab.metricPositiveShare": "Pozitif %",
    "insights.dimTab.metricNps": "NPS",
    "insights.dimTab.chartTitle": "{dimension} · {metric}",
    "insights.dimTab.totalCoverage": "Toplam {total} · Kapsama {coverage} (%{pct})",
    "insights.dimTab.percentValue": "%{value}",
    "insights.dimTab.top15Note": "İlk 15 kova gösteriliyor (adet çoğa göre sıralı).",

    // --- /insights: operasyon tab (2026-08-21) ---
    "insights.opsTab.metricSlaResolutionViolation": "Çözüm İhlal Oranı %",
    "insights.opsTab.metricSlaFirstResponseViolation": "İlk Yanıt İhlal Oranı %",
    "insights.opsTab.metricAvgResolutionTime": "Ort. Çözüm Süresi",
    "insights.opsTab.metricAvgFirstResponseTime": "Ort. İlk Yanıt Süresi",
    "insights.opsTab.coverageOf": "{count} kayıt üzerinden",
    "insights.opsTab.metricViolationRate": "İhlal Oranı %",
    "insights.opsTab.metricFirstResponseViolationRate": "İlk Yanıt İhlal Oranı %",
    "insights.opsTab.metricAvgResolution": "Ort. Çözüm Süresi",
    "insights.opsTab.metricAvgFirstResponse": "Ort. İlk Yanıt Süresi",
    "insights.opsTab.metricAvgAgentInteractions": "Ort. Temsilci Etkileşimi",
    "insights.opsTab.metricAvgCustomerInteractions": "Ort. Müşteri Etkileşimi",
    "insights.opsTab.metricCsatAvg": "Ort. CSAT",
    "insights.opsTab.slaSentimentTitle": "SLA × Duygu",
    "insights.opsTab.slaViolated": "İhlal",
    "insights.opsTab.slaWithin": "İçinde",
    "insights.opsTab.csatTitle": "CSAT",
    "insights.opsTab.csatAvgLabel": "Ortalama CSAT Skoru",
    "insights.opsTab.csatAgreementHigh":
      "CSAT 4-5 verenlerin %{pct}'si modelce POZİTİF",
    "insights.opsTab.csatAgreementLow":
      "CSAT 1-2 verenlerin %{pct}'si modelce NEGATİF",
    "insights.opsTab.lowSampleNote": "n={n} (düşük örneklem)",
    "insights.opsTab.compensationTitle": "Tazmin",
    "insights.opsTab.deliveryTitle": "Teslimat",
    "insights.opsTab.freightSum": "Navlun toplamı",
    "insights.opsTab.goodsSum": "Mal bedeli toplamı",
    "insights.opsTab.noDataHint":
      "Bu kurumda operasyonel veri (SLA, CSAT, efor, tazmin, teslimat) bulunamadı. Görmek için CSV kolon eşlemelerini Ayarlar'dan yapılandırın.",
    "insights.opsTab.noDataCta": "Operasyonel Veri Eşlemeleri'ne git →",

    // --- /insights: ısı haritası tab ---
    "insights.heatmap.xHourOfDay": "Günün Saati",
    "insights.heatmap.dayOfWeek": "Haftanın Günü",
    "insights.heatmap.weekOfYear": "Yılın Haftası",
    "insights.heatmap.month": "Ay",
    "insights.heatmap.category": "Kategori",
    "insights.heatmap.metricCount": "Yorum Sayısı",
    "insights.heatmap.metricAvgSentiment": "Ortalama Duygu",
    "insights.heatmap.metricAvgNps": "Ortalama NPS",
    "insights.heatmap.xAxis": "X ekseni",
    "insights.heatmap.yAxis": "Y ekseni",
    "insights.heatmap.metric": "Metrik",
    "insights.heatmap.sameAxisError": "X ve Y eksenleri farklı olmalı.",
    "insights.heatmap.metricScale": "{metric} skalası",
    "insights.heatmap.low": "düşük",
    "insights.heatmap.high": "yüksek",
    "insights.heatmap.legendNotePre": "Her hücre o saat × gün kesişimindeki ",
    "insights.heatmap.legendNotePost":
      " değerini gösterir. Koyu mor düşük, sarı yüksek değeri gösterir. Boş hücre = veri yok.",
    "insights.heatmap.cellEmptyTitle": "{y} × {x} — veri yok",
    "insights.heatmap.cellTitle": "{y} × {x}: {value} ({metric}) — yorumları gör",
    "insights.heatmap.cellEmptyAria": "{y} × {x} boş hücre",
    "insights.heatmap.cellAria": "{y} × {x} hücresinin yorumlarını aç",

    // --- /insights: kelime bulutu tab ---
    "insights.wordcloud.sentAll": "Tümü",
    "insights.wordcloud.sentPositive": "Pozitif",
    "insights.wordcloud.sentNegative": "Negatif",
    "insights.wordcloud.sentNeutral": "Nötr",
    "insights.wordcloud.sentiment": "Duygu",
    "insights.wordcloud.categoryFilter": "Kategori filtresi (opsiyonel)",
    "insights.wordcloud.categoryPlaceholder": "kategori_kodu",
    "insights.wordcloud.bigrams": "İkili kelimeler",
    "insights.wordcloud.title": "Kelime Bulutu",
    "insights.wordcloud.noWords": "Bu filtrelerle gösterilecek kelime yok.",
    "insights.wordcloud.wordTitle": "{text} · {weight} yorum · skew {skew}",
    "insights.wordcloud.top20": "İlk 20 Kelime",
    "insights.wordcloud.analyzedCount": "{count} yorum analiz edildi.",

    // --- paylaşılan: iş boyutu etiketleri (2026-08-20) ---
    // insights Boyutlar tab'ının boyut seçicisi, cohort tab'ın 6 yeni
    // seçeneği ve /reviews'in 6 yeni filtre dropdown'ı/pill'i AYNI
    // etiketleri kullanır — bkz. görev notu "aynı Türkçe etiketler".
    // Kurum ayarlarında (settings/business-dimensions) özel bir
    // display_label varsa Boyutlar tab'ı onu tercih eder; bu anahtarlar
    // yalnız fallback + cohort/reviews için sabit etiket.
    // NOT: "dimensions.source" (Ticket'ın kaynak boyutu — örn. Web,
    // Mobil, Mağaza) "insights.filter.source" (manuel/toplu ingest
    // yöntemi) ile KAVRAMSAL OLARAK FARKLI; ikisi de "Kaynak" diye
    // görünebilir ama ayrı filtrelerdir — görev tanımındaki birebir
    // eşleme ("Kaynak=source") bilinçli, isim çakışması kabul edildi.
    "dimensions.channel": "Taşıyıcı/Entegratör",
    "dimensions.businessSegment": "Departman",
    "dimensions.productLine": "Talep Tipi",
    "dimensions.customerTier": "Ticket Kategori",
    "dimensions.enteredBy": "Temsilci",
    "dimensions.source": "Kaynak",
    "dimensions.filterSelected": "{label}: {count} seçili",

    // --- /reviews: kaynak + duygu etiketleri ---
    "reviews.source.manual": "Manuel",
    "reviews.source.batch": "Toplu",
    "reviews.source.api": "API",
    "reviews.sentiment.negatif": "Olumsuz",
    "reviews.sentiment.pozitif": "Olumlu",
    "reviews.sentiment.notr": "Nötr",

    // --- /reviews: liste ---
    "reviews.list.title": "Analiz Arşivi",
    "reviews.list.subtitleBatch":
      "Belirli bir yüklemenin analizleri gösteriliyor.",
    "reviews.list.subtitleAll": "Tüm analizler — manuel ve toplu giriş bir arada.",
    "reviews.list.recordCount": "{count} kayıt",
    "reviews.list.emptyTitle": "Bu filtrelerle eşleşen analiz yok",
    "reviews.list.emptyHint": "Filtreleri temizleyin ya da yeni bir dosya yükleyin.",
    "reviews.list.loadMore": "Daha fazla göster",
    // F2 (2026-09-01) — aktif yükleme filtresini yeniden analiz eden
    // araç çubuğu butonu.
    "reviews.list.reanalyzeBatch": "Bu yüklemeyi yeniden analiz et",

    // --- /reviews: analiz satırı ---
    "reviews.review.removed": "kaldırılmış",
    "reviews.review.hasTicket": "Ticket var",
    "reviews.review.corrected": "düzeltildi",
    "reviews.review.openTweet": "Tweeti aç",
    "reviews.review.openSource": "Kaynağı aç",

    // --- /reviews: gün / ay etiketleri (heatmap drilldown pill'leri) ---
    "reviews.dow.0": "Pazar",
    "reviews.dow.1": "Pazartesi",
    "reviews.dow.2": "Salı",
    "reviews.dow.3": "Çarşamba",
    "reviews.dow.4": "Perşembe",
    "reviews.dow.5": "Cuma",
    "reviews.dow.6": "Cumartesi",
    "reviews.month.1": "Ocak",
    "reviews.month.2": "Şubat",
    "reviews.month.3": "Mart",
    "reviews.month.4": "Nisan",
    "reviews.month.5": "Mayıs",
    "reviews.month.6": "Haziran",
    "reviews.month.7": "Temmuz",
    "reviews.month.8": "Ağustos",
    "reviews.month.9": "Eylül",
    "reviews.month.10": "Ekim",
    "reviews.month.11": "Kasım",
    "reviews.month.12": "Aralık",

    // --- /reviews: filtre pill'leri ---
    "reviews.pill.upload": "Yükleme: {id}…",
    "reviews.pill.sentiment": "Duygu: {value}",
    "reviews.pill.source": "Kaynak: {value}",
    "reviews.pill.hour": "Saat: {value}:00",
    "reviews.pill.day": "Gün: {value}",
    "reviews.pill.week": "Hafta: {value}",
    "reviews.pill.month": "Ay: {value}",
    // WS5 (2026-08-18) — decisions/quality/date-range filtreleri +
    // pill "x" artık YALNIZ o filtreyi kaldıran buton (aria-label şart).
    "reviews.pill.decisions": "Karar: {value}",
    "reviews.pill.quality": "Veri kalitesi: {value}",
    "reviews.pill.validOnly": "Yalnız geçerli veri",
    "reviews.pill.dateRange": "Tarih: {from} – {to}",
    "reviews.pill.removeAria": "{label} filtresini kaldır",
    // 2026-08-20 — 6 boyut filtresinin ortak pill şablonu.
    "reviews.pill.dimension": "{label}: {value}",

    // --- /reviews: perspektif filtre dropdown ---
    "reviews.perspFilter.trigger": "Şirket perspektifi",
    "reviews.perspFilter.selected": "Perspektif: {count} seçili",
    "reviews.perspFilter.unmatched": "Eşleşme yok",
    "reviews.perspFilter.noTaxonomy": "Taksonomi yok.",
    "reviews.perspFilter.clearAll": "Tümünü temizle",

    // --- /reviews: duygu filtre dropdown (WS5) ---
    "reviews.sentimentFilter.trigger": "Duygu",
    "reviews.sentimentFilter.selected": "Duygu: {count} seçili",

    // --- /reviews: karar filtre dropdown (WS5) ---
    "reviews.decisionsFilter.trigger": "Karar",
    "reviews.decisionsFilter.selected": "Karar: {count} seçili",

    // --- /reviews: veri kalitesi filtre dropdown (WS5) ---
    "reviews.qualityFilter.trigger": "Veri kalitesi: Tümü",
    "reviews.qualityFilter.validOnly": "Yalnız geçerli",
    "reviews.qualityFilter.duplicate": "Tekrar",
    "reviews.qualityFilter.empty": "Boş",
    "reviews.qualityFilter.informational": "Bilgilendirme",
    "reviews.qualityFilter.meaningless": "Anlamsız",

    // --- /reviews: içerik türü çoklu-seçim filtresi — kalite
    // dropdown'ından bağımsız (content_type kalite bayrağı DEĞİL).
    "reviews.filter.contentTypes": "İçerik türü",
    "reviews.filter.contentTypesSelected": "İçerik türü: {count} seçili",
    // Risk ilk sırada — bkz. lib/types.ts CONTENT_TYPES. Filtre
    // dropdown'ı, liste rozeti ve özet panel chip'leri PAYLAŞIR.
    "reviews.contentType.escalation": "Şikâyet tehdidi",
    "reviews.contentType.request": "Talep",
    "reviews.contentType.question": "Soru",
    "reviews.contentType.suggestion": "Öneri",
    "reviews.contentType.thanks": "Teşekkür",

    // --- /reviews: tarih aralığı filtresi (WS5) ---
    "reviews.dateFilter.groupAria": "Tarih aralığı filtresi",
    "reviews.dateFilter.fromAria": "Başlangıç tarihi",
    "reviews.dateFilter.toAria": "Bitiş tarihi",

    // --- /reviews/[id]: karar etiketleri ---
    "reviews.decision.create": "Ticket Açıldı",
    "reviews.decision.skippedBelirsiz": "Atlandı (Kategori Belirsiz)",
    "reviews.decision.skippedMode": "Atlandı (Manuel Mod)",
    "reviews.decision.skippedThreshold": "Atlandı (Eşik Altı)",
    "reviews.decision.skippedDedup": "Atlandı (24s İçinde Mükerrer)",
    "reviews.decision.skippedQuality": "Atlandı (Düşük Kaliteli Veri)",

    // --- /reviews/[id]: detay ---
    "reviews.detail.promoteSuccess": "Manuel olarak Ticket açıldı.",
    "reviews.detail.noPermission": "Bu işlem için yetkin yok.",
    "reviews.detail.alreadyLinked": "Bu analiz zaten bir Ticket'a bağlı.",
    "reviews.detail.categoryNotConfigured":
      "Kategori bu kurumda yapılandırılmamış — Ticket açılamadı.",
    "reviews.detail.promoteError": "Ticket açılamadı.",
    "reviews.detail.backToList": "Analizler",
    "reviews.detail.notFound": "Analiz bulunamadı veya erişim yok.",
    "reviews.detail.analysisNo": "Analiz #{id}",
    "reviews.detail.date": "Tarih",
    "reviews.detail.analyzedAt": "Analiz tarihi",
    "reviews.detail.batchUpload": "Toplu Yükleme",
    "reviews.detail.text": "Metin",
    "reviews.detail.analysis": "Analiz",
    "reviews.detail.sentiment": "Duygu",
    "reviews.detail.scoreFinal": "Skor (final)",
    "reviews.detail.confidence": "Güven",
    "reviews.detail.percentValue": "%{value}",
    "reviews.detail.category": "Kategori",
    "reviews.detail.experience": "Deneyim",
    "reviews.experience.dijital": "Dijital",
    "reviews.experience.operasyonel": "Operasyonel",

    // --- Skor kova etiketleri (canlı) — lib/sentiment-score.ts ile
    // birlikte kullanılır: hem /reviews/[id] ana "Skor" kutusunda hem
    // "Kararı Düzelt" dialogundaki canlı etikette.
    "reviews.scoreLabel.veryNegative": "Çok olumsuz",
    "reviews.scoreLabel.negative": "Olumsuz",
    "reviews.scoreLabel.neutral": "Nötr",
    "reviews.scoreLabel.positive": "Olumlu",
    "reviews.scoreLabel.veryPositive": "Çok olumlu",

    // --- "Kararı Düzelt" dialog'u — skor/deneyim/alt-kategori (WS3,
    // 2026-08-18, migration 0042). Dialog'daki diğer metinler (başlık,
    // gerekçe vb.) bilinçli olarak eski haliyle bırakıldı — bu anahtarlar
    // yalnızca YENİ eklenen alanlara ait.
    "reviews.correct.scoreLabel": "Skor",
    "reviews.correct.scoreHint": "-1 ile 1 arasında bir değer girin.",
    "reviews.correct.scoreSliderAria": "Skor kaydırıcısı",
    "reviews.correct.scoreNumberAria": "Skor değeri",
    "reviews.correct.experienceLabel": "Deneyim",
    "reviews.correct.subcategoryLabel": "Alt kategori (şirket perspektifi)",
    "reviews.correct.noChange": "— (değiştirme)",

    "reviews.detail.companyPerspective": "Şirket Perspektifi",
    "reviews.detail.heuristicPerspective": "Heuristik perspektif",
    "reviews.detail.noMatch": "eşleşme yok",
    "reviews.detail.removedCategoryPre": "kaldırılmış kategori (kod:",
    "reviews.detail.removedCategoryPost": ")",
    "reviews.detail.ruleLayers": "Kural Katmanları",
    "reviews.detail.decision": "Karar",
    "reviews.detail.linkedTicket": "Bağlı Ticket:",
    "reviews.detail.goToTicket": "Ticket'a Git →",
    "reviews.detail.promoteButton": "Bu Analizi Ticket'a Dönüştür",
    "reviews.detail.promoteHint":
      "Elle açıldı — sistem bu karar için Ticket açmamıştı.",

    // --- /reviews/[id]: satır bazlı yeniden analiz (2026-09-01) ---
    "reviews.detail.reanalyze": "Yeniden analiz et",
    "reviews.detail.reanalyzeConfirm":
      "Bu yorum güncel modelle yeniden analiz edilsin mi? Mevcut sonuç güncellenir, insan düzeltmeleri korunur.",
    "reviews.detail.reanalyzeQueued": "Yeniden analiz kuyruğa alındı.",
    "reviews.detail.reanalyzeNotCandidate":
      "Bu yorum yeniden analiz edilemez (insan düzeltmesi var ya da içeriği boş).",
    "reviews.detail.reanalyzeNoPermission": "Yeniden analiz için yetkiniz yok.",
    "reviews.detail.reanalyzeFailed": "Yeniden analiz başlatılamadı.",

    // --- /reviews/[id]: Operasyonel Bilgiler kartı (2026-08-21) ---
    "reviews.detail.operationalInfo": "Operasyonel Bilgiler",
    "reviews.detail.facts.slaWithin": "SLA İçinde",
    "reviews.detail.facts.slaViolated": "SLA İhlali",
    "reviews.detail.facts.slaResolutionStatus": "Çözüm SLA Durumu",
    "reviews.detail.facts.slaFirstResponseStatus": "İlk Yanıt SLA Durumu",
    "reviews.detail.facts.resolutionTime": "Çözüm Süresi",
    "reviews.detail.facts.firstResponseTime": "İlk Yanıt Süresi",
    "reviews.detail.facts.csat": "Anket (CSAT)",
    "reviews.detail.facts.agentInteractions": "Temsilci Etkileşimleri",
    "reviews.detail.facts.customerInteractions": "Müşteri Etkileşimleri",
    "reviews.detail.facts.compensationStatus": "Tazmin Onay Durumu",
    "reviews.detail.facts.freightCost": "Navlun Bedeli",
    "reviews.detail.facts.goodsCost": "Mal Bedeli",
    "reviews.detail.facts.refundReason": "İade Sebebi",
    "reviews.detail.facts.deliveryStatus": "Teslimat Durumu",
    "reviews.detail.facts.deliveryDetail": "Teslimat Durumu Detayı",

    // --- /reviews/[id]: Twitter etkileşim rozetleri (2026-09-01) ---
    "reviews.detail.engagement.like": "Beğeni",
    "reviews.detail.engagement.retweet": "Retweet",
    "reviews.detail.engagement.reply": "Yanıt",
    "reviews.detail.engagement.view": "Görüntülenme",

    // --- /reviews: filtreye tepki veren özet paneli (W3) ---
    "reviews.summary.panelTitle": "Filtre Özeti",
    "reviews.summary.loading": "Özet yükleniyor…",
    "reviews.summary.loadError": "Özet şu an yüklenemedi; yorum listesi bundan etkilenmez.",
    "reviews.summary.emptyTitle": "Bu filtrelerle eşleşen veri yok",
    "reviews.summary.headline.recordCount": "{count} kayıt",
    "reviews.summary.headline.avgScore": "Ortalama skor",
    "reviews.summary.headline.noScore": "Skor yok",
    "reviews.summary.headline.lowN": "Az veri — {count} yorum",
    "reviews.summary.headline.ticketLinked": "{count} Ticket'a bağlı",
    "reviews.summary.sentiment.title": "Duygu dağılımı",
    "reviews.summary.contentTypes.title": "İçerik türleri",
    "reviews.summary.contentTypes.escalationHint":
      "Önce şikâyet tehdidi içeren yorumlara bakın.",
    "reviews.summary.nps.title": "NPS",
    "reviews.summary.nps.promoter": "Destekçi",
    "reviews.summary.nps.passive": "Pasif",
    "reviews.summary.nps.detractor": "Kötüleyen",
    "reviews.summary.nps.score": "NPS skoru {score}",
    "reviews.summary.nps.responses": "{count} yanıt",
    "reviews.summary.nps.insufficientN": "NPS için yeterli yanıt yok ({count} yanıt)",
    "reviews.summary.daily.title": "Günlük eğilim",
    "reviews.summary.daily.barAria": "{date}: {count} yorum, {negative} negatif",
    "reviews.summary.categories.title": "En çok kategoriler",
    "reviews.summary.sources.title": "Kaynaklar",
    "reviews.summary.enteredBy.title": "Temsilci / veri kalitesi",
    "reviews.summary.enteredBy.colValue": "Temsilci",
    "reviews.summary.enteredBy.colTotal": "Toplam",
    "reviews.summary.enteredBy.colFlagged": "Geçersiz",
    "reviews.summary.enteredBy.colQuestion": "Soru",
    "reviews.summary.enteredBy.colNegative": "Negatif",
    "reviews.summary.questions.title": "En çok sorulanlar",
    "reviews.summary.questions.totalCount": "{count} soru toplam",
    "reviews.summary.quality.title": "Veri kalitesi kırılımı",
    "reviews.summary.quality.clean": "Temiz",

    // --- /reports: tip + durum etiketleri ---
    "reports.type.comprehensive": "Kapsamlı",
    "reports.type.reviewsOnly": "Sadece Yorumlar",
    "reports.type.ticketsOnly": "Sadece Ticket'lar",
    "reports.status.queued": "Sırada",
    "reports.status.generating": "Üretiliyor",
    "reports.status.completed": "Tamamlandı",
    "reports.status.failed": "Başarısız",

    // --- /reports: sayfa + tablo ---
    "reports.page.title": "Raporlar",
    "reports.page.subtitle":
      "Excel veya CSV olarak çok-sayfalı analiz + Ticket raporları üretip 24 saat boyunca indirin.",
    "reports.newReport": "Yeni Rapor",
    "reports.generatingMid": "raporu üretiliyor… durum:",
    "reports.emptyPre": "Henüz rapor yok. Üstteki ",
    "reports.emptyPost": " butonu ile ilk raporunuzu üretebilirsiniz.",
    "reports.table.date": "Tarih",
    "reports.table.type": "Tip",
    "reports.table.format": "Format",
    "reports.table.rows": "Satır",
    "reports.table.size": "Boyut",
    "reports.table.status": "Durum",
    "reports.download": "İndir",
    "reports.deleteConfirm": "Raporu silmek istediğinizden emin misiniz?",
    "reports.deleteError": "Silinemedi.",
    "reports.deleteSuccess": "Rapor silindi.",
    "reports.downloadError": "İndirilemedi: {status} {detail}",
    "reports.downloadStartError": "İndirme başlatılamadı.",

    // --- /reports: yeni rapor modalı ---
    "reports.estimateError": "Tahmin alınamadı.",
    "reports.queuedSuccess": "Rapor sıraya alındı.",
    "reports.generateError": "Rapor üretilemedi.",
    "reports.modalTitle": "Yeni Rapor — Adım {step}/3",
    "reports.close": "Kapat",
    "reports.back": "Geri",
    "reports.continue": "Devam",
    "reports.preview": "Önizleme",
    "reports.generate": "Üret",
    "reports.hardLimit": "Hard limit: 90 gün, 50.000 satır.",
    "reports.reportType": "Rapor Tipi",
    "reports.dateRange": "Tarih Aralığı",
    "reports.thisMonth": "Bu ay",
    "reports.lastMonth": "Geçen ay",
    "reports.thisQuarter": "Bu çeyrek",
    "reports.rangeDays": "Aralık: {days} gün",
    "reports.rangeOverLimit": " — 90 gün limitini aşıyor.",
    "reports.est.rows": "Tahmini satır:",
    "reports.est.time": "Tahmini süre:",
    "reports.est.seconds": "~{n} saniye",
    "reports.est.type": "Tip:",
    "reports.est.format": "Format:",
    "reports.est.dateRange": "Tarih aralığı:",
    "reports.est.reviewRows": "Analiz satırı:",
    "reports.est.ticketRows": "Ticket satırı:",

    // --- paylaşılan charts/heatmap ---
    "charts.heatmapAria": "Isı haritası",
  },
  en: {
    // --- /insights: tabs ---
    "insights.tabs.sentiment": "Sentiment",
    "insights.tabs.category": "Category",
    "insights.tabs.nps": "NPS",
    "insights.tabs.cross": "Cross",
    "insights.tabs.perspective": "Perspective",
    "insights.tabs.tickets": "Ticket",
    "insights.tabs.heatmap": "Heatmap",
    "insights.tabs.cohort": "Cohort",
    "insights.tabs.wordcloud": "Words",
    "insights.tabs.overrides": "Rule Layers",
    // 2026-08-20 — Dimensions tab (business dimension breakdown).
    "insights.tabs.dimensions": "Dimensions",
    // 2026-08-21 — Operations tab (SLA/CSAT/effort/compensation/delivery).
    "insights.tabs.operations": "Operations",

    // --- /insights: page header ---
    "insights.page.title": "Insights",
    "insights.page.subtitle":
      "Detailed view of sentiment, category, and Ticket metrics.",

    // --- /insights: filter bar ---
    "insights.filter.allTime": "All time",
    "insights.filter.noFilterHint":
      "No filter applied — narrow down by choosing a start and end date.",
    "insights.filter.startDate": "Start",
    "insights.filter.endDate": "End",
    "insights.filter.source": "Source",
    "insights.filter.sourceAll": "All",
    "insights.filter.sourceManualOnly": "Manual only",
    "insights.filter.sourceBatchOnly": "Batch only",

    // --- 2026-08-18 (Wave 3, WS2): data quality include_flagged toggle ---
    // Shared component (/insights + dashboard filter bar).
    "insights.filter.includeFlaggedLabel": "Include low-quality data",
    "insights.filter.includeFlaggedAria": "Include low-quality data",
    "insights.filter.includeFlaggedBadge":
      "includes duplicate/empty/informational rows",

    // --- /insights: shared state messages ---
    "insights.state.loadError": "Failed to load data: {message}",
    "insights.state.loadErrorShort": "Failed to load data.",
    "insights.state.noData": "No data found for these filters.",
    "insights.state.noValue": "no data",

    // --- /insights: chart titles / notes ---
    "insights.chart.sentimentDistribution": "Sentiment Distribution",
    "insights.chart.scoreHistogram": "Score Histogram",
    "insights.chart.sentimentTrendDaily": "Sentiment Trend (daily)",
    "insights.chart.categoryTop10": "Top 10 Categories",
    "insights.chart.categorySentimentMatrix": "Category × Sentiment Matrix",
    "insights.chart.matrixTooltip": "{row} × {col}: {value} analyses",
    "insights.chart.belirsizNote":
      "The \"Belirsiz\" (unclassifiable) category covers comments that couldn't be classified — a large number usually comes from overly broad or very short comments. It's moved to the end of the table to make the signals easier to see.",
    "insights.chart.ruleLayers": "Rule Layers",
    "insights.chart.ruleLayersNotePre":
      "The rule-layer counts will be populated in Sprint 8.3.4 (",
    "insights.chart.ruleLayersNotePost":
      "JSONB column); for now the 5 layers show with zero counts.",
    "insights.chart.npsScore": "NPS Score",
    "insights.chart.npsResponsesCoverage": "{count} responses · {coverage}% coverage",
    "insights.chart.bucketDistribution": "Bucket Distribution",
    "insights.chart.monthlyTrend12": "Monthly Trend (last 12 months)",
    "insights.chart.companyPerspectiveTop10": "Top 10 Company Perspectives",
    "insights.chart.unmatchedLabel": "No match:",
    "insights.chart.analysesCount": "{count} analyses",
    "insights.chart.unmatchedHint": "(didn't match a heuristic taxonomy entry).",
    "insights.chart.resolutionTimeDistribution": "Resolution Time Distribution",
    "insights.chart.avg": "Average",
    "insights.chart.median": "Median",
    "insights.chart.hours": "{value} h",

    // --- /insights: cohort tab ---
    "insights.cohort.periodWeek": "Week",
    "insights.cohort.periodMonth": "Month",
    "insights.cohort.periodQuarter": "Quarter",
    "insights.cohort.dimTaxonomy": "Category",
    "insights.cohort.dimPerspective": "Company Perspective",
    "insights.cohort.dimNpsBucket": "NPS Bucket",
    "insights.cohort.period": "Period",
    "insights.cohort.dimension": "Dimension",
    "insights.cohort.topCohorts": "Top cohorts",
    "insights.cohort.trendTitle": "Cohort Trend",

    // --- /insights: dimensions tab (2026-08-20) ---
    "insights.dimTab.dimension": "Dimension",
    "insights.dimTab.metric": "Metric",
    "insights.dimTab.metricVolume": "Comment Count",
    "insights.dimTab.metricNegativeShare": "Negative Share %",
    "insights.dimTab.metricAvgScore": "Average Score",
    "insights.dimTab.metricPositiveShare": "Positive %",
    "insights.dimTab.metricNps": "NPS",
    "insights.dimTab.chartTitle": "{dimension} · {metric}",
    "insights.dimTab.totalCoverage": "Total {total} · Coverage {coverage} ({pct}%)",
    "insights.dimTab.percentValue": "{value}%",
    "insights.dimTab.top15Note": "Showing the first 15 buckets (ordered by count desc).",

    // --- /insights: operations tab (2026-08-21) ---
    "insights.opsTab.metricSlaResolutionViolation": "Resolution Violation Rate %",
    "insights.opsTab.metricSlaFirstResponseViolation": "First Response Violation Rate %",
    "insights.opsTab.metricAvgResolutionTime": "Avg. Resolution Time",
    "insights.opsTab.metricAvgFirstResponseTime": "Avg. First Response Time",
    "insights.opsTab.coverageOf": "based on {count} records",
    "insights.opsTab.metricViolationRate": "Violation Rate %",
    "insights.opsTab.metricFirstResponseViolationRate": "First Response Violation Rate %",
    "insights.opsTab.metricAvgResolution": "Avg. Resolution Time",
    "insights.opsTab.metricAvgFirstResponse": "Avg. First Response Time",
    "insights.opsTab.metricAvgAgentInteractions": "Avg. Agent Interactions",
    "insights.opsTab.metricAvgCustomerInteractions": "Avg. Customer Interactions",
    "insights.opsTab.metricCsatAvg": "Avg. CSAT",
    "insights.opsTab.slaSentimentTitle": "SLA × Sentiment",
    "insights.opsTab.slaViolated": "Violated",
    "insights.opsTab.slaWithin": "Within",
    "insights.opsTab.csatTitle": "CSAT",
    "insights.opsTab.csatAvgLabel": "Average CSAT Score",
    "insights.opsTab.csatAgreementHigh":
      "{pct}% of CSAT 4-5 respondents were scored POSITIVE by the model",
    "insights.opsTab.csatAgreementLow":
      "{pct}% of CSAT 1-2 respondents were scored NEGATIVE by the model",
    "insights.opsTab.lowSampleNote": "n={n} (low sample size)",
    "insights.opsTab.compensationTitle": "Compensation",
    "insights.opsTab.deliveryTitle": "Delivery",
    "insights.opsTab.freightSum": "Freight cost total",
    "insights.opsTab.goodsSum": "Goods cost total",
    "insights.opsTab.noDataHint":
      "No operational data (SLA, CSAT, effort, compensation, delivery) found for this organization. Configure the CSV column mappings in Settings to see it.",
    "insights.opsTab.noDataCta": "Go to Operational Data Mappings →",

    // --- /insights: heatmap tab ---
    "insights.heatmap.xHourOfDay": "Hour of Day",
    "insights.heatmap.dayOfWeek": "Day of Week",
    "insights.heatmap.weekOfYear": "Week of Year",
    "insights.heatmap.month": "Month",
    "insights.heatmap.category": "Category",
    "insights.heatmap.metricCount": "Comment Count",
    "insights.heatmap.metricAvgSentiment": "Average Sentiment",
    "insights.heatmap.metricAvgNps": "Average NPS",
    "insights.heatmap.xAxis": "X axis",
    "insights.heatmap.yAxis": "Y axis",
    "insights.heatmap.metric": "Metric",
    "insights.heatmap.sameAxisError": "The X and Y axes must be different.",
    "insights.heatmap.metricScale": "{metric} scale",
    "insights.heatmap.low": "low",
    "insights.heatmap.high": "high",
    "insights.heatmap.legendNotePre": "Each cell shows the ",
    "insights.heatmap.legendNotePost":
      " value at that hour × day intersection. Dark purple marks low values, yellow marks high. Empty cell = no data.",
    "insights.heatmap.cellEmptyTitle": "{y} × {x} — no data",
    "insights.heatmap.cellTitle": "{y} × {x}: {value} ({metric}) — view comments",
    "insights.heatmap.cellEmptyAria": "{y} × {x} empty cell",
    "insights.heatmap.cellAria": "Open comments for the {y} × {x} cell",

    // --- /insights: word cloud tab ---
    "insights.wordcloud.sentAll": "All",
    "insights.wordcloud.sentPositive": "Positive",
    "insights.wordcloud.sentNegative": "Negative",
    "insights.wordcloud.sentNeutral": "Neutral",
    "insights.wordcloud.sentiment": "Sentiment",
    "insights.wordcloud.categoryFilter": "Category filter (optional)",
    "insights.wordcloud.categoryPlaceholder": "category_code",
    "insights.wordcloud.bigrams": "Bigrams",
    "insights.wordcloud.title": "Word Cloud",
    "insights.wordcloud.noWords": "No words to show for these filters.",
    "insights.wordcloud.wordTitle": "{text} · {weight} comments · skew {skew}",
    "insights.wordcloud.top20": "Top 20 Words",
    "insights.wordcloud.analyzedCount": "{count} comments analysed.",

    // --- shared: business dimension labels (2026-08-20) ---
    // Used by the Insights Dimensions tab's dimension picker, the
    // cohort tab's 6 new options, and /reviews' 6 new filter dropdowns
    // / pills — same labels everywhere per the task spec. The
    // Dimensions tab prefers the tenant's configured display_label
    // (settings/business-dimensions) when one exists; these keys are
    // the fallback + the fixed label for cohort/reviews.
    // NOTE: "dimensions.source" (the review's source dimension — e.g.
    // Web, Mobile, Store) is conceptually DIFFERENT from
    // "insights.filter.source" (manual/batch ingest method) — both
    // can read "Source" but they're separate filters. The 1:1 mapping
    // ("Kaynak"="source") is deliberate per the task spec; the name
    // overlap is accepted, not an oversight.
    "dimensions.channel": "Carrier/Integrator",
    "dimensions.businessSegment": "Department",
    "dimensions.productLine": "Request Type",
    "dimensions.customerTier": "Ticket Category",
    "dimensions.enteredBy": "Agent",
    "dimensions.source": "Source",
    "dimensions.filterSelected": "{label}: {count} selected",

    // --- /reviews: source + sentiment labels ---
    "reviews.source.manual": "Manual",
    "reviews.source.batch": "Batch",
    "reviews.source.api": "API",
    "reviews.sentiment.negatif": "Negative",
    "reviews.sentiment.pozitif": "Positive",
    "reviews.sentiment.notr": "Neutral",

    // --- /reviews: list ---
    "reviews.list.title": "Analysis Archive",
    "reviews.list.subtitleBatch": "Showing analyses from a specific upload.",
    "reviews.list.subtitleAll":
      "All analyses — manual and batch entries together.",
    "reviews.list.recordCount": "{count} records",
    "reviews.list.emptyTitle": "No analyses match these filters",
    "reviews.list.emptyHint": "Clear the filters or upload a new file.",
    "reviews.list.loadMore": "Show more",
    // F2 (2026-09-01) — toolbar button that re-analyses the active
    // upload filter.
    "reviews.list.reanalyzeBatch": "Re-analyse this upload",

    // --- /reviews: review row ---
    "reviews.review.removed": "removed",
    "reviews.review.hasTicket": "Has Ticket",
    "reviews.review.corrected": "corrected",
    "reviews.review.openTweet": "Open tweet",
    "reviews.review.openSource": "Open source",

    // --- /reviews: day / month labels (heatmap drilldown pills) ---
    "reviews.dow.0": "Sunday",
    "reviews.dow.1": "Monday",
    "reviews.dow.2": "Tuesday",
    "reviews.dow.3": "Wednesday",
    "reviews.dow.4": "Thursday",
    "reviews.dow.5": "Friday",
    "reviews.dow.6": "Saturday",
    "reviews.month.1": "January",
    "reviews.month.2": "February",
    "reviews.month.3": "March",
    "reviews.month.4": "April",
    "reviews.month.5": "May",
    "reviews.month.6": "June",
    "reviews.month.7": "July",
    "reviews.month.8": "August",
    "reviews.month.9": "September",
    "reviews.month.10": "October",
    "reviews.month.11": "November",
    "reviews.month.12": "December",

    // --- /reviews: filter pills ---
    "reviews.pill.upload": "Upload: {id}…",
    "reviews.pill.sentiment": "Sentiment: {value}",
    "reviews.pill.source": "Source: {value}",
    "reviews.pill.hour": "Hour: {value}:00",
    "reviews.pill.day": "Day: {value}",
    "reviews.pill.week": "Week: {value}",
    "reviews.pill.month": "Month: {value}",
    // WS5 (2026-08-18) — decisions/quality/date-range filters + the
    // pill "x" now removes only that one filter (needs an aria-label).
    "reviews.pill.decisions": "Decision: {value}",
    "reviews.pill.quality": "Data quality: {value}",
    "reviews.pill.validOnly": "Valid data only",
    "reviews.pill.dateRange": "Date: {from} – {to}",
    "reviews.pill.removeAria": "Remove {label} filter",
    // 2026-08-20 — shared pill template for the 6 dimension filters.
    "reviews.pill.dimension": "{label}: {value}",

    // --- /reviews: perspective filter dropdown ---
    "reviews.perspFilter.trigger": "Company perspective",
    "reviews.perspFilter.selected": "Perspective: {count} selected",
    "reviews.perspFilter.unmatched": "No match",
    "reviews.perspFilter.noTaxonomy": "No taxonomy.",
    "reviews.perspFilter.clearAll": "Clear all",

    // --- /reviews: sentiment filter dropdown (WS5) ---
    "reviews.sentimentFilter.trigger": "Sentiment",
    "reviews.sentimentFilter.selected": "Sentiment: {count} selected",

    // --- /reviews: decision filter dropdown (WS5) ---
    "reviews.decisionsFilter.trigger": "Decision",
    "reviews.decisionsFilter.selected": "Decision: {count} selected",

    // --- /reviews: data quality filter dropdown (WS5) ---
    "reviews.qualityFilter.trigger": "Data quality: All",
    "reviews.qualityFilter.validOnly": "Valid only",
    "reviews.qualityFilter.duplicate": "Duplicate",
    "reviews.qualityFilter.empty": "Empty",
    "reviews.qualityFilter.informational": "Informational",
    "reviews.qualityFilter.meaningless": "Meaningless",

    // --- /reviews: content-type multi-select filter — independent of
    // the quality dropdown (content_type is NOT a quality flag).
    "reviews.filter.contentTypes": "Content type",
    "reviews.filter.contentTypesSelected": "Content type: {count} selected",
    // Risk first — see lib/types.ts CONTENT_TYPES. Shared by the filter
    // dropdown, the list badge, and the summary panel chips.
    "reviews.contentType.escalation": "Escalation threat",
    "reviews.contentType.request": "Request",
    "reviews.contentType.question": "Question",
    "reviews.contentType.suggestion": "Suggestion",
    "reviews.contentType.thanks": "Thanks",

    // --- /reviews: date range filter (WS5) ---
    "reviews.dateFilter.groupAria": "Date range filter",
    "reviews.dateFilter.fromAria": "Start date",
    "reviews.dateFilter.toAria": "End date",

    // --- /reviews/[id]: decision labels ---
    "reviews.decision.create": "Ticket Opened",
    "reviews.decision.skippedBelirsiz": "Skipped (Category Unclear)",
    "reviews.decision.skippedMode": "Skipped (Manual Mode)",
    "reviews.decision.skippedThreshold": "Skipped (Below Threshold)",
    "reviews.decision.skippedDedup": "Skipped (Duplicate Within 24h)",
    "reviews.decision.skippedQuality": "Skipped (Low-Quality Data)",
    // NOTE: the backend's new "skipped_quality" branch (migration 0042)
    // is deliberately absent here — see lib/types.ts ReviewDecision.

    // --- /reviews/[id]: detail ---
    "reviews.detail.promoteSuccess": "Ticket opened manually.",
    "reviews.detail.noPermission": "You don't have permission for this action.",
    "reviews.detail.alreadyLinked": "This analysis is already linked to a Ticket.",
    "reviews.detail.categoryNotConfigured":
      "Category is not configured for this organization — could not open a Ticket.",
    "reviews.detail.promoteError": "Couldn't open a Ticket.",
    "reviews.detail.backToList": "Analyses",
    "reviews.detail.notFound": "Analysis not found or no access.",
    "reviews.detail.analysisNo": "Analysis #{id}",
    "reviews.detail.date": "Date",
    "reviews.detail.analyzedAt": "Analyzed at",
    "reviews.detail.batchUpload": "Batch Upload",
    "reviews.detail.text": "Text",
    "reviews.detail.analysis": "Analysis",
    "reviews.detail.sentiment": "Sentiment",
    "reviews.detail.scoreFinal": "Score (final)",
    "reviews.detail.confidence": "Confidence",
    "reviews.detail.percentValue": "{value}%",
    "reviews.detail.category": "Category",
    "reviews.detail.experience": "Experience",
    "reviews.experience.dijital": "Digital",
    "reviews.experience.operasyonel": "Operational",

    // --- Score bucket labels (live) — used together with
    // lib/sentiment-score.ts: both in /reviews/[id]'s main "Score" tile
    // and the live label in the "Correct the decision" dialog.
    "reviews.scoreLabel.veryNegative": "Very negative",
    "reviews.scoreLabel.negative": "Negative",
    "reviews.scoreLabel.neutral": "Neutral",
    "reviews.scoreLabel.positive": "Positive",
    "reviews.scoreLabel.veryPositive": "Very positive",

    // --- "Correct the decision" dialog — score/experience/subcategory
    // (WS3, 2026-08-18, migration 0042). The dialog's other strings
    // (title, reason field, etc.) are deliberately left as-is — these
    // keys cover only the NEWLY added fields.
    "reviews.correct.scoreLabel": "Score",
    "reviews.correct.scoreHint": "Enter a value between -1 and 1.",
    "reviews.correct.scoreSliderAria": "Score slider",
    "reviews.correct.scoreNumberAria": "Score value",
    "reviews.correct.experienceLabel": "Experience",
    "reviews.correct.subcategoryLabel": "Subcategory (company perspective)",
    "reviews.correct.noChange": "— (no change)",

    "reviews.detail.companyPerspective": "Company Perspective",
    "reviews.detail.heuristicPerspective": "Heuristic perspective",
    "reviews.detail.noMatch": "no match",
    "reviews.detail.removedCategoryPre": "removed category (code:",
    "reviews.detail.removedCategoryPost": ")",
    "reviews.detail.ruleLayers": "Rule Layers",
    "reviews.detail.decision": "Decision",
    "reviews.detail.linkedTicket": "Linked Ticket:",
    "reviews.detail.goToTicket": "Go to Ticket →",
    "reviews.detail.promoteButton": "Convert This Analysis to a Ticket",
    "reviews.detail.promoteHint":
      "Opened manually — the system hadn't opened a Ticket for this decision.",

    // --- /reviews/[id]: per-review re-analysis (2026-09-01) ---
    "reviews.detail.reanalyze": "Re-analyse",
    "reviews.detail.reanalyzeConfirm":
      "Re-analyse this review with the current model? The existing result will be updated; human corrections are preserved.",
    "reviews.detail.reanalyzeQueued": "Re-analysis queued.",
    "reviews.detail.reanalyzeNotCandidate":
      "This review can't be re-analysed (it has a human correction or empty content).",
    "reviews.detail.reanalyzeNoPermission":
      "You don't have permission to re-analyse.",
    "reviews.detail.reanalyzeFailed": "Couldn't start the re-analysis.",

    // --- /reviews/[id]: Operational Info card (2026-08-21) ---
    "reviews.detail.operationalInfo": "Operational Information",
    "reviews.detail.facts.slaWithin": "Within SLA",
    "reviews.detail.facts.slaViolated": "SLA Violated",
    "reviews.detail.facts.slaResolutionStatus": "Resolution SLA Status",
    "reviews.detail.facts.slaFirstResponseStatus": "First Response SLA Status",
    "reviews.detail.facts.resolutionTime": "Resolution Time",
    "reviews.detail.facts.firstResponseTime": "First Response Time",
    "reviews.detail.facts.csat": "Survey (CSAT)",
    "reviews.detail.facts.agentInteractions": "Agent Interactions",
    "reviews.detail.facts.customerInteractions": "Customer Interactions",
    "reviews.detail.facts.compensationStatus": "Compensation Approval Status",
    "reviews.detail.facts.freightCost": "Freight Cost",
    "reviews.detail.facts.goodsCost": "Goods Cost",
    "reviews.detail.facts.refundReason": "Refund Reason",
    "reviews.detail.facts.deliveryStatus": "Delivery Status",
    "reviews.detail.facts.deliveryDetail": "Delivery Status Detail",

    // --- /reviews/[id]: Twitter engagement chips (2026-09-01) ---
    "reviews.detail.engagement.like": "Likes",
    "reviews.detail.engagement.retweet": "Retweets",
    "reviews.detail.engagement.reply": "Replies",
    "reviews.detail.engagement.view": "Views",

    // --- /reviews: filter-reactive summary panel (W3) ---
    "reviews.summary.panelTitle": "Filter Summary",
    "reviews.summary.loading": "Loading summary…",
    "reviews.summary.loadError": "The summary couldn't load right now — the review list isn't affected.",
    "reviews.summary.emptyTitle": "No data matches these filters",
    "reviews.summary.headline.recordCount": "{count} records",
    "reviews.summary.headline.avgScore": "Average score",
    "reviews.summary.headline.noScore": "No score",
    "reviews.summary.headline.lowN": "Low data — {count} reviews",
    "reviews.summary.headline.ticketLinked": "{count} linked to a Ticket",
    "reviews.summary.sentiment.title": "Sentiment distribution",
    "reviews.summary.contentTypes.title": "Content types",
    "reviews.summary.contentTypes.escalationHint":
      "Start with the reviews that threaten escalation.",
    "reviews.summary.nps.title": "NPS",
    "reviews.summary.nps.promoter": "Promoter",
    "reviews.summary.nps.passive": "Passive",
    "reviews.summary.nps.detractor": "Detractor",
    "reviews.summary.nps.score": "NPS score {score}",
    "reviews.summary.nps.responses": "{count} responses",
    "reviews.summary.nps.insufficientN": "Not enough responses for NPS ({count})",
    "reviews.summary.daily.title": "Daily trend",
    "reviews.summary.daily.barAria": "{date}: {count} comments, {negative} negative",
    "reviews.summary.categories.title": "Top categories",
    "reviews.summary.sources.title": "Sources",
    "reviews.summary.enteredBy.title": "Agent / data quality",
    "reviews.summary.enteredBy.colValue": "Agent",
    "reviews.summary.enteredBy.colTotal": "Total",
    "reviews.summary.enteredBy.colFlagged": "Invalid",
    "reviews.summary.enteredBy.colQuestion": "Question",
    "reviews.summary.enteredBy.colNegative": "Negative",
    "reviews.summary.questions.title": "Most asked",
    "reviews.summary.questions.totalCount": "{count} questions total",
    "reviews.summary.quality.title": "Data quality breakdown",
    "reviews.summary.quality.clean": "Clean",

    // --- /reports: type + status labels ---
    "reports.type.comprehensive": "Comprehensive",
    "reports.type.reviewsOnly": "Reviews Only",
    "reports.type.ticketsOnly": "Tickets Only",
    "reports.status.queued": "Queued",
    "reports.status.generating": "Generating",
    "reports.status.completed": "Completed",
    "reports.status.failed": "Failed",

    // --- /reports: page + table ---
    "reports.page.title": "Reports",
    "reports.page.subtitle":
      "Generate multi-sheet analysis + Ticket reports as Excel or CSV and download them for 24 hours.",
    "reports.newReport": "New Report",
    "reports.generatingMid": "report is generating… status:",
    "reports.emptyPre": "No reports yet. Use the ",
    "reports.emptyPost": " button above to generate your first report.",
    "reports.table.date": "Date",
    "reports.table.type": "Type",
    "reports.table.format": "Format",
    "reports.table.rows": "Rows",
    "reports.table.size": "Size",
    "reports.table.status": "Status",
    "reports.download": "Download",
    "reports.deleteConfirm": "Are you sure you want to delete the report?",
    "reports.deleteError": "Couldn't delete.",
    "reports.deleteSuccess": "Report deleted.",
    "reports.downloadError": "Download failed: {status} {detail}",
    "reports.downloadStartError": "Couldn't start the download.",

    // --- /reports: new report modal ---
    "reports.estimateError": "Couldn't get an estimate.",
    "reports.queuedSuccess": "Report queued.",
    "reports.generateError": "Couldn't generate the report.",
    "reports.modalTitle": "New Report — Step {step}/3",
    "reports.close": "Close",
    "reports.back": "Back",
    "reports.continue": "Continue",
    "reports.preview": "Preview",
    "reports.generate": "Generate",
    "reports.hardLimit": "Hard limit: 90 days, 50,000 rows.",
    "reports.reportType": "Report Type",
    "reports.dateRange": "Date Range",
    "reports.thisMonth": "This month",
    "reports.lastMonth": "Last month",
    "reports.thisQuarter": "This quarter",
    "reports.rangeDays": "Range: {days} days",
    "reports.rangeOverLimit": " — exceeds the 90-day limit.",
    "reports.est.rows": "Estimated rows:",
    "reports.est.time": "Estimated time:",
    "reports.est.seconds": "~{n} seconds",
    "reports.est.type": "Type:",
    "reports.est.format": "Format:",
    "reports.est.dateRange": "Date range:",
    "reports.est.reviewRows": "Analysis rows:",
    "reports.est.ticketRows": "Ticket rows:",

    // --- shared charts/heatmap ---
    "charts.heatmapAria": "Heatmap",
  },
};
