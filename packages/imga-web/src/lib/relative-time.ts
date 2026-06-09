// Sprint 10.0 — Türkçe göreli zaman ("3 gün önce", "az önce").
//
// C-level dashboard kartları mutlak tarih yerine göreli zaman
// gösterir — "12.05.2026" yerine "3 gün önce" yöneticiye tazelik
// hissi verir. dd.mm.yyyy formatı (UML Madde 9) tooltip'te kalır;
// caller `title` attribute'una `formatDateTr` koyabilir.

export function relativeTimeTr(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "az önce";
  if (minutes < 60) return `${minutes} dk önce`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} saat önce`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} gün önce`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} ay önce`;
  const years = Math.floor(months / 12);
  return `${years} yıl önce`;
}

export function formatDateTr(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}.${d.getFullYear()}`;
}
