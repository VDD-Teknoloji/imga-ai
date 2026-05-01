// Tek noktadan Türkçe tarih formatlama yardımcıları.
//
// Sprint 7.7.2'ye kadar her bileşen kendi `formatRelativeDate` /
// `formatTimelineDate` / `formatDate` kopyasını taşıyordu. Birleştirilen
// versiyon hem tek tip Türkçe çıktı verir hem de yeni Comments / Timeline
// bileşenlerinin de aynı şekli kullanmasını sağlar.

const TR_LOCALE = "tr-TR";

/**
 * Göreceli zaman ("az önce", "3 sa önce", "2 gün önce"). 7 günden eski
 * tarihleri tam tarih olarak (gün ay yıl) gösterir.
 */
export function formatRelativeDate(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  if (diffHours < 1) return "az önce";
  if (diffHours < 24) return `${diffHours} sa önce`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays} gün önce`;
  return date.toLocaleDateString(TR_LOCALE, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Timeline / yorum karelerinde kullanılan kısa Türkçe tarih + saat
 * (örn. "5 May 14:32"). Aynı gün içinde olsa bile tam saat gösterilir
 * çünkü timeline ardışık olayları ayırt etmek için saat hassasiyetine
 * ihtiyaç duyar.
 */
export function formatTimelineDate(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(TR_LOCALE, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Yan panellerde / metadata satırlarında kullanılan tam Türkçe tarih
 * (örn. "5 Mayıs 2026 14:32").
 */
export function formatFullDate(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(TR_LOCALE, {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
