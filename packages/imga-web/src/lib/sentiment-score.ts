// Skor kovası eşikleri — imga-core config.py SENTIMENT_NEGATIVE_THRESHOLD /
// SENTIMENT_POSITIVE_THRESHOLD (±0.05 nötr bandı) ile birebir aynı sınır.
// Bu değerler orada değişirse burada da güncellenmeli.

export type SentimentScoreBucket =
  | "veryNegative"
  | "negative"
  | "neutral"
  | "positive"
  | "veryPositive";

export function sentimentScoreBucket(score: number): SentimentScoreBucket {
  if (score < -0.6) return "veryNegative";
  if (score < -0.05) return "negative";
  if (score <= 0.05) return "neutral";
  if (score <= 0.6) return "positive";
  return "veryPositive";
}
