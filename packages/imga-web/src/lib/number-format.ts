// Süper-admin envanter sayfaları (tenants tablosu + /admin/usage) için
// paylaşılan sayı formatlayıcılar.
//
// null/undefined tek noktadan "—" düşer — çağıranlar kendi ternary'lerini
// yazmasın diye (aksi halde her tabloda ayrı bir null-check kopyası
// birikir).

/**
 * Kompakt token/satır sayısı: "1,2M", "45K" gibi — Türkçe virgüllü ondalık.
 *
 * `Intl.NumberFormat("tr-TR", {notation:"compact"})` KASITLI olarak
 * kullanılmadı: gerçek çıktısı "1,2 Mn" / "45 B" (B = bin, milyon değil)
 * — görev metnindeki "1,2M" örneğiyle uyuşmuyor ve "B" tr-TR'de bin
 * demek, milyar değil (doğrulandı: `node -e` ile Intl çıktısı test
 * edildi). Milyar+ ölçek bu ürün için gerçekçi değil (kurum başına 30
 * günlük token sayısı) — o eşiğin üstünde gruplu tam sayıya düşülüyor,
 * "B" harfini milyar için hiç kullanmayarak bin/milyar karışıklığından
 * tamamen kaçınıyoruz.
 */
export function formatCompactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs < 1_000) return value.toLocaleString("tr-TR");
  if (abs < 1_000_000_000) {
    const [divisor, suffix] = abs < 1_000_000 ? [1_000, "K"] : [1_000_000, "M"];
    const scaled = Math.round((value / divisor) * 10) / 10;
    const text = Number.isInteger(scaled) ? String(scaled) : scaled.toFixed(1).replace(".", ",");
    return `${text}${suffix}`;
  }
  // Milyar+ — bkz. üstteki not, "B" harfi burada kullanılmıyor.
  return value.toLocaleString("tr-TR");
}

const USD_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumSignificantDigits: 2,
  maximumSignificantDigits: 4,
});

/**
 * USD tutarı, 2-4 anlamlı basamak (görev talebi: "$0.000001 hassasiyetiyle
 * değil"). en-US locale KASITLI: tr-TR'de $ + nokta-binlik-ayraç
 * kombinasyonu "$1.235" gibi yanlış okunabilecek bir gösterim üretiyor
 * (1234.5 → tr-TR'de "1.235" görünür ama bu 1235 demek, 1,235 dolar
 * değil — `node -e` ile doğrulandı). USD her zaman standart $1,234.56
 * biçiminde kalır, sayfanın geri kalanı Türkçe olsa da.
 *
 * 0 özel durumu: formatter'ın kendi haliyle "$0.0" üretir (minimumSignificantDigits
 * sıfırda da 2 basamak zorluyor) — "$0.0" kırık görünüyor, gerçek sıfır
 * maliyeti düz "$0" olarak gösteriyoruz. null/undefined (bilinmiyor) "—".
 */
export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value === 0) return "$0";
  return USD_FORMATTER.format(value);
}
