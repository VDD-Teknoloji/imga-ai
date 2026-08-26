/** Kaynak bağlantısının düğme etiketi: x.com / twitter.com → "Tweeti aç",
 *  diğer her şey → "Kaynağı aç". Liste satırı ham 'kaynak' değerini
 *  taşımadığından etiket URL'den türetilir. Arşiv kartı ve detay sayfası
 *  aynı yardımcıyı kullanır (page dosyaları default dışında export
 *  veremediği için ayrı modül). */
export function sourceLinkLabelKey(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^(www\.|mobile\.)/, "");
    if (host === "x.com" || host === "twitter.com") {
      return "reviews.review.openTweet";
    }
  } catch {
    // Geçersiz URL — genel etiket.
  }
  return "reviews.review.openSource";
}
