# Navlungo duygu analizi benchmark'ı — BERT vs 5 LLM (2026-08-10)

Navlungo Test kurumunun 9.902 yorumu (ağırlıkla kargo destek yazışması:
takip soruları, FedEx/UPS bilgilendirme e-postaları, teslimat sorunları)
üzerinde, mevcut BERT hattı ile 5 OpenRouter modeli sıfırdan karşılaştırıldı.
Ayrıntılı sonuçlar: `2026-08-10-navlungo-llm-benchmark.xlsx`.

## Yöntem

- **Referans seti:** 500 satırlık katmanlı örneklem. İki güçlü model
  (claude-sonnet-5 + gpt-5.4) bağımsız etiketledi; %90 anlaşma. Kalan 50
  anlaşmazlık tek tek insan-denetimli okunarak karara bağlandı.
  Nihai dağılım: NÖTR 320 / NEGATIF 174 / POZITIF 6.
- **Mevcut sistem doğrulaması:** BERT+kural katmanları çevrimdışı yeniden
  koşuldu; 9.902 satırın **tamamında** kayıtlı üretim etiketleriyle birebir
  aynı çıktı. Yani üretimdeki etiketlerin kaynağı klasik BERT hattı
  (audit'teki Gemini çağrıları kategori yardımcısı).
- Adaylar aynı Türkçe prompt + 25'li batch'lerle tüm veri setini etiketledi.
  Koşular sunucuda, kaynak sınırlı konteynerlerde.

## Sonuç tablosu (referans 500 üzerinde)

| Sistem | Doğruluk | Ağırlıklı F1 | NEGATIF recall | Kapsam (9.902) | ~10k yorum maliyeti |
|---|---|---|---|---|---|
| Gemini 3.6 Flash | %95,2 | 0.952 | 0.913 | 8.376 (%85) | $8,28 |
| **GLM 5.2** | **%92,8** | **0.927** | **0.862** | **9.902 (%100)** | **$0,24** |
| DeepSeek v4 Pro | %89,4 | 0.900 | 0.851 | 9.900 | $1,71 |
| GPT-5.6 Luna | %88,5 | 0.888 | 0.980 | 8.602 | $0,24 |
| Claude Haiku 4.5 | %87,5 | 0.883 | 0.933 | 8.875 | $1,91 |
| Mevcut (BERT+katmanlar) | %29,0 | 0.282 | 0.730 | 9.902 | — |

Mevcut sistemin sınıf detayı: POZITIF precision **0.022** (POZITIF dediklerinin
%2'si gerçekten pozitif), NÖTR recall **0.038**. BERT, nötr işlem
mesajlarını ("kargom nerede", doğrulama e-postaları, gümrük bilgilendirmeleri)
kitlesel olarak POZITIF'e yazıyor — kullanıcı şikayetinin kök nedeni bu.

## Öneri

1. **GLM 5.2 (`z-ai/glm-5.2`)** varsayılan sınıflandırma modeli yapılmalı:
   fiyat/performans açık ara en iyi (%92,8 doğruluk, tam kapsam, 10 bin yorum
   ≈ $0,24). Süper admin panelinden kurumun OpenRouter kimliğinde model
   olarak seçilmesi yeterli.
2. En yüksek kalite şartsa **Gemini 3.6 Flash** (%95,2) — 34 kat pahalı ve
   bu koşuda %15 satır kaybı yaşadı (üretimdeki structured-output yolu bu
   kaybı azaltır; yine de güvenilirlik sinyali GLM lehine).
3. **GPT-5.6 Luna** ucuz ve NEGATIF recall'u en yüksek (0.980) — "hiçbir
   şikayeti kaçırma" öncelikli senaryoda alternatif.
4. Mevcut BERT hattı yalnızca LLM erişilemezken acil yedek olarak kalmalı.

## Kısıtlar

- Referans setinde yalnızca 6 gerçek POZITIF var (veri seti destek
  yazışması ağırlıklı); POZITIF sınıfı ölçümü zayıf. Pazaryeri yorumu gibi
  övgü ağırlıklı bir veri setinde ayrıca doğrulama önerilir.
- Kapsam kayıpları (Gemini/GPT/Haiku) bu düzeneğin serbest-JSON çağrısından;
  üretim yolu structured output kullandığından fark kapanabilir.
- Maliyetler OpenRouter liste fiyatlarıyla, batch indirimsiz hesaplandı.
