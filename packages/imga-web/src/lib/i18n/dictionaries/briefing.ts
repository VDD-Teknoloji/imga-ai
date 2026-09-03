import type { Bundle } from "./types";

/**
 * briefing alan sözlüğü (2026-09-03 — /executive-briefing yeniden tasarımı).
 *
 * Kapsam: Yönetici Özeti sayfası — manşet kartı, KPI kutucukları, kritik
 * içgörüler, öncelikli aksiyonlar, geçmiş özetler listesi. Sayfa öncesinde
 * hiç t() çağrısı taşımıyordu (tüm metin sabit TR); bu modül onu tamamen
 * kapsar. dashboard.quickLinks.briefing.* (başka bileşenin anahtarları)
 * dashboard.ts'de kalır, buraya taşınmaz.
 */
export const briefing: Bundle = {
  tr: {
    "briefing.page.title": "Yönetici Özeti",
    "briefing.page.subtitle":
      "Otomatik dönemsel özet — KPI değişimleri, kritik içgörüler ve öncelikli aksiyonlar.",
    "briefing.page.loading": "Yükleniyor…",

    // --- LLM anahtarı yok banner'ı ---
    "briefing.banner.title": "Yönetici özeti oluşturmak için bir LLM anahtarı gerekli.",
    "briefing.banner.desc": "En az bir aktif anahtar tanımlanana kadar üretim devre dışı.",
    "briefing.banner.cta": "Anahtar ekle",

    // --- üretim satırı ---
    "briefing.period.label": "Dönem",
    "briefing.period.week": "Hafta",
    "briefing.period.month": "Ay",
    "briefing.period.quarter": "Çeyrek",
    "briefing.generate.button": "Yeni özet üret",
    "briefing.schedule.cta": "Zamanla",
    "briefing.toast.success": "Brifing hazır.",
    "briefing.toast.errorGeneric": "Brifing üretilemedi.",

    // --- boş / yükleniyor durumları ---
    "briefing.empty.title": "Henüz brifing yok.",
    "briefing.empty.desc":
      "Aşağıdaki form ile ilk dönemsel özeti üretin — KPI değişimleri, kritik içgörüler ve öncelikli aksiyonlar hazırlanır.",
    "briefing.detail.loading": "Brifing yükleniyor…",

    // --- manşet kartı ---
    "briefing.hero.aria": "Brifing manşeti",
    "briefing.hero.periodTile.label": "Dönem",
    "briefing.hero.periodTile.range": "{from} – {to}",

    // --- KPI kutucukları ---
    "briefing.kpi.newLabel": "yeni başlangıç",
    "briefing.kpi.previous": "önceki: {value}",

    // --- kritik içgörüler ---
    "briefing.findings.title": "Kritik İçgörüler",
    "briefing.findings.showMore": "Devamını gör",
    "briefing.findings.showLess": "Daha az göster",

    // --- öncelikli aksiyonlar ---
    "briefing.actions.title": "Öncelikli Aksiyonlar",

    // --- aksiyon durum rozeti ---
    "briefing.status.open": "Açık",
    "briefing.status.inProgress": "Devam ediyor",
    "briefing.status.done": "Tamamlandı",
    "briefing.status.cancelled": "İptal",

    // --- geçmiş özetler ---
    "briefing.history.title": "Geçmiş Özetler",
    "briefing.history.loading": "Yükleniyor…",
    "briefing.history.empty": "Henüz brifing yok.",
    "briefing.history.selectedAria": "Şu an görüntülenen brifing",
    "briefing.history.viewAria": "{headline} brifingini görüntüle",
  },
  en: {
    "briefing.page.title": "Executive Summary",
    "briefing.page.subtitle":
      "Automated periodic summary — KPI changes, critical insights, and top actions.",
    "briefing.page.loading": "Loading…",

    // --- no LLM key banner ---
    "briefing.banner.title": "An LLM key is required to generate executive summaries.",
    "briefing.banner.desc": "Generation stays disabled until at least one active key is set up.",
    "briefing.banner.cta": "Add key",

    // --- generation row ---
    "briefing.period.label": "Period",
    "briefing.period.week": "Week",
    "briefing.period.month": "Month",
    "briefing.period.quarter": "Quarter",
    "briefing.generate.button": "Generate new summary",
    "briefing.schedule.cta": "Schedule",
    "briefing.toast.success": "Summary is ready.",
    "briefing.toast.errorGeneric": "Could not generate summary.",

    // --- empty / loading states ---
    "briefing.empty.title": "No summaries yet.",
    "briefing.empty.desc":
      "Use the form below to generate the first periodic summary — KPI changes, critical insights, and top actions get prepared.",
    "briefing.detail.loading": "Loading summary…",

    // --- headline card ---
    "briefing.hero.aria": "Summary headline",
    "briefing.hero.periodTile.label": "Period",
    "briefing.hero.periodTile.range": "{from} – {to}",

    // --- KPI tiles ---
    "briefing.kpi.newLabel": "new baseline",
    "briefing.kpi.previous": "previous: {value}",

    // --- critical insights ---
    "briefing.findings.title": "Critical Insights",
    "briefing.findings.showMore": "Show more",
    "briefing.findings.showLess": "Show less",

    // --- top actions ---
    "briefing.actions.title": "Top Actions",

    // --- action status badge ---
    "briefing.status.open": "Open",
    "briefing.status.inProgress": "In progress",
    "briefing.status.done": "Done",
    "briefing.status.cancelled": "Cancelled",

    // --- history ---
    "briefing.history.title": "Past Summaries",
    "briefing.history.loading": "Loading…",
    "briefing.history.empty": "No summaries yet.",
    "briefing.history.selectedAria": "Currently viewed summary",
    "briefing.history.viewAria": "View the {headline} summary",
  },
};
