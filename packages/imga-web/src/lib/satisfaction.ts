// Ana sayfa hero manşeti + "Deneyim skoru" — F (2026-09-02, home-liveliness).
//
// Ürün sahibi talimatı: "Müşterilerinizin bir kısmı memnun değil" gibi
// muğlak bir cümle yerine, tek bakışta çarpan bir SAYI ifadesi
// ("Her 5 yorumdan 1'i şikâyet"). Üç bant, tek payda üzerinden
// (negShare = negatif / toplam):
//   >= %20  şikâyet ağırlıklı  -> "Her N yorumdan 1'i şikâyet"
//   %5-%20  büyük çoğunluk iyi -> "Her N yorumdan (N-1)'i sorunsuz"
//   < %5    iyi durumda        -> "Yorumların %P'i sorunsuz"
// n = Math.max(2, Math.round(1/negShare)): 1/negShare "kaç yorumdan
// biri şikâyet" sorusunun cevabı; taban 2 "her 1 yorumdan 1'i" gibi
// anlamsız bir ifadeyi engeller.

export type SatisfactionHeadline =
  | { band: "complaint"; n: number }
  | { band: "mostlyFine"; n: number; nMinus1: number }
  | { band: "fine"; pct: number };

const COMPLAINT_THRESHOLD = 0.2;
const MOSTLY_FINE_THRESHOLD = 0.05;

export function satisfactionHeadline(
  positive: number,
  neutral: number,
  negative: number,
): SatisfactionHeadline {
  const total = positive + neutral + negative;
  if (total <= 0) return { band: "fine", pct: 100 };
  const negShare = negative / total;
  if (negShare >= COMPLAINT_THRESHOLD) {
    return { band: "complaint", n: Math.max(2, Math.round(1 / negShare)) };
  }
  if (negShare >= MOSTLY_FINE_THRESHOLD) {
    const n = Math.max(2, Math.round(1 / negShare));
    return { band: "mostlyFine", n, nMinus1: n - 1 };
  }
  return { band: "fine", pct: Math.round((1 - negShare) * 100) };
}

/** "Deneyim skoru": ortalama duygu skorunu (-1..+1) 0-100 ölçeğine
 *  haritalar. Şikâyet kanalları doğası gereği olumsuza yatkındır
 *  (memnun müşteri nadiren yazar) — bu yüzden yorum SAYMAK yerine
 *  ortalama duygu YOĞUNLUĞUNU gösteriyoruz (ScoreInfoTip metni). */
export function experienceScoreFromAvg(avgSentimentScore: number): number {
  return Math.round(((avgSentimentScore + 1) / 2) * 100);
}

/** avg_sentiment_score yokken (eski API) ya da hero'nun gösterdiği
 *  segmentli çubukla FARKLI bir popülasyona (yükleme/kalite filtresi)
 *  karşılık geldiğinde kullanılan basit net-duygu yedeği — aynı -1..+1
 *  ölçeğinde, POZİTİF/NEGATİF sayımından türetilir (nötr paydaya girer
 *  ama pay/payda dengesini bozmaz). Hero'daki popülasyon-uyuşmazlığı
 *  notuna bkz. (executive-hero.tsx). */
export function pseudoSentimentScore(positive: number, negative: number, total: number): number {
  return total > 0 ? (positive - negative) / total : 0;
}

// --- Türkçe iyelik eki (-I) ------------------------------------------
//
// PO'nun literal manşet metni rakama iyelik eki ekliyor ("3.267
// yorumun 2.189'u", "%97'si") — sabit bir "'i" çoğu değer için
// yanlış olur (ünlü uyumu + kaynaştırma 's'si sayının TÜRKÇE OKUNUŞUNA
// göre değişir). Bu yardımcı, sayının son okunan sözcüğüne (birler
// basamağı sıfır değilse birler sözcüğü, sıfırsa onlar/yüz sözcüğü)
// göre doğru eki döner. Yalnız 0-100 aralığı doğrulandı — bu dosyanın
// ürettiği manşet değişkenleri (nMinus1, pct) bu aralığı aşmıyor.
interface PossessiveInfo {
  /** Sözcük ünlüyle bitiyorsa kaynaştırma 's'si eklenir (iki -> ikisi). */
  buffered: boolean;
  vowel: "ı" | "i" | "u" | "ü";
}

// bir, iki, üç, dört, beş, altı, yedi, sekiz, dokuz (+ sıfır, 0 index —
// pratikte hiç üretilmiyor ama tabloyu tam tutar).
const UNITS: readonly PossessiveInfo[] = [
  { buffered: false, vowel: "ı" }, // 0 sıfır
  { buffered: false, vowel: "i" }, // 1 bir
  { buffered: true, vowel: "i" }, // 2 iki
  { buffered: false, vowel: "ü" }, // 3 üç
  { buffered: false, vowel: "ü" }, // 4 dört
  { buffered: false, vowel: "i" }, // 5 beş
  { buffered: true, vowel: "ı" }, // 6 altı
  { buffered: true, vowel: "i" }, // 7 yedi
  { buffered: false, vowel: "i" }, // 8 sekiz
  { buffered: false, vowel: "u" }, // 9 dokuz
];

// on, yirmi, otuz, kırk, elli, altmış, yetmiş, seksen, doksan.
const TENS: Readonly<Record<number, PossessiveInfo>> = {
  10: { buffered: false, vowel: "u" },
  20: { buffered: true, vowel: "i" },
  30: { buffered: false, vowel: "u" },
  40: { buffered: false, vowel: "ı" },
  50: { buffered: true, vowel: "i" },
  60: { buffered: false, vowel: "ı" },
  70: { buffered: false, vowel: "i" },
  80: { buffered: false, vowel: "i" },
  90: { buffered: false, vowel: "ı" },
};

const HUNDRED: PossessiveInfo = { buffered: false, vowel: "ü" }; // yüz

export function turkishPossessiveSuffix(n: number): string {
  const abs = Math.abs(Math.trunc(n));
  const info =
    abs === 100 ? HUNDRED : abs > 0 && abs % 10 === 0 ? (TENS[abs] ?? UNITS[0]!) : UNITS[abs % 10]!;
  return info.buffered ? `s${info.vowel}` : info.vowel;
}
