import type { Bundle } from "./types";

/**
 * compare alan sözlüğü (WS4, 2026-08-18).
 *
 * Kapsam: /compare — iki dönemi (Dönem A / Dönem B) karşılaştıran KPI +
 * dağılım sayfası. Ortak "Yükleniyor…" gibi metinler core.ts'teki
 * common.* anahtarlarını yeniden kullanır (insights.ts'teki konvansiyon).
 */
export const compare: Bundle = {
  tr: {
    "compare.page.title": "Karşılaştır",
    "compare.page.subtitle":
      "İki dönemi yan yana karşılaştırın — toplam yorum, duygu, kategori, NPS ve ortalama skor değişimi.",

    // --- hızlı çift presetler ---
    "compare.pair.label": "Hızlı karşılaştırma",
    "compare.pair.lastMonthVsThisMonth": "Geçen ay vs Bu ay",
    "compare.pair.lastWeekVsThisWeek": "Geçen hafta vs Bu hafta",

    // --- dönem grupları ---
    "compare.group.a": "Dönem A",
    "compare.group.b": "Dönem B",
    "compare.group.aAria": "Dönem A tarih seçimi",
    "compare.group.bAria": "Dönem B tarih seçimi",
    "compare.group.rangeLabel": "{from} – {to}",

    // --- hızlı presetler (tek dönem) ---
    "compare.preset.thisMonth": "Bu ay",
    "compare.preset.lastMonth": "Geçen ay",
    "compare.preset.thisWeek": "Bu hafta",
    "compare.preset.lastWeek": "Geçen hafta",

    // --- ay gezgini ---
    "compare.monthNav.prevAria": "Önceki ay",
    "compare.monthNav.nextAria": "Sonraki ay",
    "compare.monthNav.apply": "Bu ayı uygula",
    "compare.month.1": "Ocak",
    "compare.month.2": "Şubat",
    "compare.month.3": "Mart",
    "compare.month.4": "Nisan",
    "compare.month.5": "Mayıs",
    "compare.month.6": "Haziran",
    "compare.month.7": "Temmuz",
    "compare.month.8": "Ağustos",
    "compare.month.9": "Eylül",
    "compare.month.10": "Ekim",
    "compare.month.11": "Kasım",
    "compare.month.12": "Aralık",

    // --- serbest tarih aralığı ---
    "compare.custom.label": "Serbest aralık",
    "compare.custom.fromAria": "Başlangıç tarihi",
    "compare.custom.toAria": "Bitiş tarihi",

    // --- sayfa durumları ---
    "compare.state.loading": "Karşılaştırma yükleniyor…",
    "compare.state.incompleteRange":
      "Her iki dönem için de geçerli bir başlangıç/bitiş tarihi seçin.",
    "compare.state.loadError": "Karşılaştırma yüklenemedi: {message}",
    "compare.state.noPeriodData": "Bu dönemde veri yok.",

    // --- KPI delta kartları ---
    "compare.kpi.totalReviews": "Toplam Yorum",
    "compare.kpi.nps": "NPS",
    "compare.kpi.avgScore": "Ortalama Skor",
    "compare.kpi.negativeShare": "Olumsuz Payı",
    "compare.kpi.noValue": "—",
    "compare.kpi.pointsSuffix": "puan",
    "compare.kpi.aValue": "A: {value}",
    "compare.kpi.bValue": "B: {value}",

    // --- duygu dağılımı ---
    "compare.section.sentiment": "Duygu Dağılımı",
    "compare.sentiment.NEGATIF": "Olumsuz",
    "compare.sentiment.NÖTR": "Nötr",
    "compare.sentiment.POZITIF": "Olumlu",

    // --- kategori dağılımı ---
    "compare.section.category": "Kategori Dağılımı (ilk 8)",
    "compare.section.categoryNote":
      "B döneminde en çok görülen 8 kategori. Rozet = kategorinin toplam yorum içindeki payındaki değişim (B − A, yüzde puan); NEGATİF pay bazlı değildir.",
    "compare.category.empty": "Kategori verisi yok.",

    // --- deneyim dağılımı ---
    "compare.section.experience": "Deneyim Dağılımı",
    "compare.experience.digital": "Dijital",
    "compare.experience.operational": "Operasyonel",
    "compare.experience.unassigned": "Atanmamış",
    "compare.experience.negativeOf": "{count} olumsuz",

    // --- iyileşen/kötüleşen şeridi ---
    "compare.strip.title": "Hangi kategoride değişim oldu",
    "compare.strip.subtitle":
      "Kategorinin toplam yorum payındaki en büyük değişimler (B − A, yüzde puan) — NEGATİF pay bazlı değil, toplam pay bazlıdır.",
    "compare.strip.improved": "Payı en çok azalan 3 kategori",
    "compare.strip.worsened": "Payı en çok artan 3 kategori",
    "compare.strip.empty": "Yeterli kategori verisi yok.",

    // --- yön etiketleri (ekran okuyucu) ---
    "compare.direction.up": "arttı",
    "compare.direction.down": "azaldı",
    "compare.direction.flat": "değişmedi",
  },
  en: {
    "compare.page.title": "Compare",
    "compare.page.subtitle":
      "Compare two periods side by side — total reviews, sentiment, category, NPS, and average score change.",

    // --- quick pair presets ---
    "compare.pair.label": "Quick comparison",
    "compare.pair.lastMonthVsThisMonth": "Last month vs This month",
    "compare.pair.lastWeekVsThisWeek": "Last week vs This week",

    // --- period groups ---
    "compare.group.a": "Period A",
    "compare.group.b": "Period B",
    "compare.group.aAria": "Period A date selection",
    "compare.group.bAria": "Period B date selection",
    "compare.group.rangeLabel": "{from} – {to}",

    // --- single-period quick presets ---
    "compare.preset.thisMonth": "This month",
    "compare.preset.lastMonth": "Last month",
    "compare.preset.thisWeek": "This week",
    "compare.preset.lastWeek": "Last week",

    // --- month navigator ---
    "compare.monthNav.prevAria": "Previous month",
    "compare.monthNav.nextAria": "Next month",
    "compare.monthNav.apply": "Apply this month",
    "compare.month.1": "January",
    "compare.month.2": "February",
    "compare.month.3": "March",
    "compare.month.4": "April",
    "compare.month.5": "May",
    "compare.month.6": "June",
    "compare.month.7": "July",
    "compare.month.8": "August",
    "compare.month.9": "September",
    "compare.month.10": "October",
    "compare.month.11": "November",
    "compare.month.12": "December",

    // --- free date range ---
    "compare.custom.label": "Custom range",
    "compare.custom.fromAria": "Start date",
    "compare.custom.toAria": "End date",

    // --- page states ---
    "compare.state.loading": "Loading comparison…",
    "compare.state.incompleteRange":
      "Pick a valid start/end date for both periods.",
    "compare.state.loadError": "Could not load comparison: {message}",
    "compare.state.noPeriodData": "No data for this period.",

    // --- KPI delta cards ---
    "compare.kpi.totalReviews": "Total Reviews",
    "compare.kpi.nps": "NPS",
    "compare.kpi.avgScore": "Average Score",
    "compare.kpi.negativeShare": "Negative Share",
    "compare.kpi.noValue": "—",
    "compare.kpi.pointsSuffix": "pts",
    "compare.kpi.aValue": "A: {value}",
    "compare.kpi.bValue": "B: {value}",

    // --- sentiment distribution ---
    "compare.section.sentiment": "Sentiment Distribution",
    "compare.sentiment.NEGATIF": "Negative",
    "compare.sentiment.NÖTR": "Neutral",
    "compare.sentiment.POZITIF": "Positive",

    // --- category distribution ---
    "compare.section.category": "Category Distribution (top 8)",
    "compare.section.categoryNote":
      "Top 8 categories in Period B. Badge = change in the category's share of total reviews (B − A, percentage points); not based on the NEGATIVE share.",
    "compare.category.empty": "No category data.",

    // --- experience distribution ---
    "compare.section.experience": "Experience Distribution",
    "compare.experience.digital": "Digital",
    "compare.experience.operational": "Operational",
    "compare.experience.unassigned": "Unassigned",
    "compare.experience.negativeOf": "{count} negative",

    // --- improved/worsened strip ---
    "compare.strip.title": "Where things changed",
    "compare.strip.subtitle":
      "Largest changes in a category's share of total reviews (B − A, percentage points) — based on total share, not the NEGATIVE share.",
    "compare.strip.improved": "Top 3 shrinking categories",
    "compare.strip.worsened": "Top 3 growing categories",
    "compare.strip.empty": "Not enough category data.",

    // --- direction labels (screen reader) ---
    "compare.direction.up": "up",
    "compare.direction.down": "down",
    "compare.direction.flat": "unchanged",
  },
};
