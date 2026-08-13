# imga.ai Sınıflandırma Rehberi v2 (kanonik)

Tek kaynak: referans etiketleme, üretim prompt'u ve değerlendirme bu
dokümandan türetilir.

## 1. Duygu (s)

- **NEGATIF** — Yazan kişi bir sorunu, gecikmeyi, kaybı, tutarsızlığı,
  hasarı, ulaşamamayı, cevapsızlığı RAPOR EDİYOR ya da şikayet ediyor.
  Nazik dil sorunu örtmez: "rica ederim, gönderim 12 gündür hareketsiz"
  → NEGATIF. İroni/alay ("harika, yine kayboldu") → NEGATIF.
- **POZITIF** — Yazan kişi memnuniyet, teşekkür, övgü İFADE EDİYOR ve
  mesajın özü bu. Yalnızca kibar kapanış ("teşekkürler") POZITIF yapmaz.
- **NÖTR** — Duygu içermeyen her şey: bilgi talebi, durum sorusu,
  belge/işlem talebi, otomatik bildirim, doğrulama/OTP e-postası,
  taşıyıcı bilgilendirmesi, operasyonel talimat, adres/detay iletimi.
  Şüphede kural: mesajda ne açık bir sorun raporu ne övgü varsa NÖTR.

Sınır kuralları:
- Sorun İMASI yetmez; sorun ifadesi gerekir. "Kargom nerede?" tek başına
  NÖTR; "Kargom 5 gündür nerede, güncelleme yok" NEGATIF.
- Çözülmüş sorun bildirimi ("teslim edildi, case kapatalım") NÖTR;
  çözüm için açık teşekkür/memnuniyet varsa POZITIF.
- Karma duyguda baskın öğe seçilir; skor orta banda çekilir.

## 2. Duygu skoru (sc) — bant kalibrasyonu

| Bant | Aralık | Tanım | Örnek |
|---|---|---|---|
| Güçlü negatif | -1.0 … -0.7 | Ağır kayıp/öfke/tehdit, tekrarlayan mağduriyet | "12 gündür kayıp, kimse dönmüyor, rezalet" |
| Orta negatif | -0.6 … -0.4 | Net sorun raporu, sabırlı ton | "Gönderi teslim edilememiş, yardımcı olur musunuz" |
| Hafif negatif | -0.3 … -0.1 | Küçük aksaklık, hafif rahatsızlık | "Biraz geç ulaştı" |
| Nötr | -0.05 … 0.05 | Duygu yok | Durum sorusu, bildirim |
| Hafif pozitif | 0.1 … 0.3 | Küçük memnuniyet notu | "Sorunsuz geldi" |
| Orta pozitif | 0.4 … 0.6 | Açık memnuniyet | "Hızlı teslimat, teşekkürler" |
| Güçlü pozitif | 0.7 … 1.0 | Coşkulu övgü, tavsiye | "Muhteşem hizmet, herkese öneririm" |

Kural: NÖTR etikete |sc| ≤ 0.05; hafif ifadeye asla ±0.7+ verilmez.

## 3. Ana kategori (c) — tanımlar ve sınırlar

- **kargo** (Kargo / Lojistik) — Taşıma ve teslimatın KENDİSİ: gecikme,
  kayıp, hareketsiz gönderi, yanlış adrese teslim, teslim edilememe,
  takip statüsü tutarsızlığı, gümrükte bekleme, taşıyıcı (FedEx/UPS…)
  süreçleri. Taşıyıcıdan gelen bilgilendirme e-postaları da buraya.
- **faturalama** (Faturalama / Ödeme) — Ücret, fiyat farkı, fatura
  kesimi/düzeltmesi, vergi/gümrük ÜCRETLERİ, iade edilen para, tahsilat.
  (Gümrükte BEKLEME kargo'dur; gümrük VERGİSİ tartışması faturalama.)
- **urun_kalitesi** (Ürün Kalitesi) — Ürünün fiziksel durumu: hasarlı,
  kırık, eksik parça, yanlış ürün, ambalaj kaynaklı hasar.
- **musteri_hizmetleri** (Müşteri Hizmetleri) — Destek DENEYİMİNİN
  kendisi: cevapsızlık, geç dönüş, yanlış bilgi verilmesi, ilgisizlik,
  ya da destek ekibine övgü. (Sorunun konusu başka kategoriyse ve
  şikayet desteğin tutumuna DEĞİLSE o kategori seçilir.)
- **iade** (İade / Değişim) — İade/değişim SÜRECİ: iade talebi, iade
  onayı, geri gönderim, değişim işlemleri. (İade PARASI gecikmesi
  faturalama'ya gider; iade kargosunun kaybolması kargo'ya.)
- **teknik_destek** (Teknik Destek) — Yazılım/platform arızası: site
  veya uygulama hatası, giriş yapamama, takip kodunun sistemde
  çalışmaması, entegrasyon/API sorunu, buton/ekran hatası.
- **siparis_sureci** (Sipariş Süreci) — Sipariş oluşturma/işleme:
  sipariş verememe, yanlış sipariş kaydı, etiket/konşimento oluşturma,
  gönderi kaydı düzeltmeleri, evrak talepleri (fatura örneği hariç).
- **pazarlama** (Pazarlama / İletişim) — Kampanya, indirim, duyuru,
  tanıtım içeriği ve bunlarla ilgili şikayet/soru.
- **belirsiz** — YALNIZCA metin anlamlı bir konu taşımıyorsa (boşa
  yakın, bağlamsız, tek kelime, anlaşılamayan). Konusu olan hiçbir
  mesaj belirsiz OLMAMALI; emin olunamıyorsa en yakın kategori + düşük
  cc tercih edilir.

## 4. Deneyim türü (e) — YENİ, kategoriden bağımsız eksen

Soru: müşterinin yaşadığı temas noktası DİJİTAL mi FİZİKSEL mi?

- **dijital** — Sorun/etkileşim ekranda yaşanıyor: uygulama, web sitesi,
  takip EKRANI (statü yanlış/güncellenmiyor dahil), online ödeme akışı,
  e-posta/SMS bildirimlerinin gelmemesi, giriş/hesap, API.
  ÖRN: "Uygulamada teslim edildi görünüyor ama paket gelmedi" → kategori
  kargo olabilir ama deneyim DİJİTAL (yanlış gösteren şey ekran).
- **operasyonel** — Sorun fiziksel dünyada: paketin kendisi, kurye,
  depo, gümrük süreci, teslimat adresi, ürün durumu, çağrı merkezi.
- **(boş)** — İkisine de oturmuyorsa alan yazılmaz.

Kural: kategori ≠ deneyim. Her kategoriden yorum her iki deneyime
düşebilir; ayrımı temas noktası belirler.

## 5. Alt kategori (p)

Seçilen ana kategorinin listesinden; hiçbiri uymuyorsa yazılmaz.
Liste dışı kod asla üretilmez.
