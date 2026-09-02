import type { Bundle } from "./types";

/**
 * rootCause alan sözlüğü (Sprint 13.3, F2).
 *
 * Kapsam: dashboard/root-cause-cards.tsx'in bu sprintte eklenen
 * yüzeyleri — last_error'a bağlı boş-durum kopyası, uzman notu bloğu,
 * "Aksiyona çevir" mikro-akışı, süreç verisi linki. dashboard.ts başka
 * bir ajanın dosyası olduğundan yeni anahtarlar oraya değil buraya
 * eklendi (görev talimatı — prefix "rootCause.").
 */
export const rootCause: Bundle = {
  tr: {
    // --- boş durum: last_error'a göre kopya (dashboard.rootCauseCards.empty.desc'in yerini alır) ---
    "rootCause.error.noCredentials":
      "Kök neden analizi çalıştırılamadı: kurum için tanımlı bir LLM anahtarı yok. Anahtarı imga ekibi tanımlar.",
    "rootCause.error.noCredentialsCta": "Anahtar tanımla",
    "rootCause.error.failed": "Son otomatik analiz başarısız oldu; yeni bir yükleme yeniden dener.",

    // --- uzman notu (nedenin detayında, kanıt alıntılarından sonra) ---
    "rootCause.expertNote.label": "Uzman notu",

    // --- "Aksiyona çevir" ---
    "rootCause.convert.button": "Aksiyona çevir",
    "rootCause.convert.done": "Aksiyon oluşturuldu",
    "rootCause.convert.error": "Aksiyon oluşturulamadı. Tekrar deneyin.",

    // --- süreç verisi linki ---
    "rootCause.processLink": "Süreç verisine bak",
  },
  en: {
    "rootCause.error.noCredentials":
      "Root-cause analysis failed to run: no LLM key is configured for this tenant. The imga team sets it up.",
    "rootCause.error.noCredentialsCta": "Set up a key",
    "rootCause.error.failed": "The last automatic analysis failed; the next upload will retry it.",

    "rootCause.expertNote.label": "Expert note",

    "rootCause.convert.button": "Create action",
    "rootCause.convert.done": "Action created",
    "rootCause.convert.error": "Couldn't create the action. Try again.",

    "rootCause.processLink": "See process data",
  },
};
