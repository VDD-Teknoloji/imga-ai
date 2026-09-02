# Düzeltmeler neden genellenmiyor — analiz ve ilk iyileştirme (2026-09-02)

Ürün sahibinin gözlemi: bir yorumu düzeltiyoruz ama aynı tür hata başka
yorumlarda tekrarlanıyor. Bu doküman bugünkü mekanizmayı sade anlatır,
kod okumasıyla doğrulanmış nedenleri sıralar, bu turda yapılanı ve
kalan planı verir.

## 1. Düzeltmeler bugün nasıl çalışıyor

Bir yorumu "Kararı düzelt" ile değiştirdiğinizde üç şey olur:

- Yorumun kendi kaydı anında güncellenir.
- Düzeltme bir arşive yazılır: eski karar, yeni karar, yorum metni,
  mümkünse metnin "anlam vektörü" (embedding).
- Bu arşiv üç şekilde gelecekteki analizlere yansır:
  1. **Birebir eşleşme** — aynı metin (yazım farkları göz ardı
     edilerek) tekrar gelirse, yapay zekaya hiç sorulmadan son insan
     kararı uygulanır.
  2. **Örnek gösterme (few-shot)** — "geçmişte insanlar böyle karar
     verdi, örnek al" diye en güncel ve anlamca en yakın düzeltmeler
     prompt'a eklenir. Bu **tavsiye** — model isterse farklı karar
     verebilir.
  3. **Anlamsal doğrudan devralma** — yeni yorum, arşivdeki bir
     düzeltmeye anlam olarak neredeyse birebir yakınsa (eş anlamlı,
     yazım farklı) insan kararı otomatik uygulanır, model sorulmaz.
     Eşik **bilinçli sıkı** — yanlış bir otomatik devralma kalıcı
     hale gelir (bkz. §2).

Bu üç katman toplu analizde ve "Yeniden analiz et"te **zaten aktif**
— "düzeltmeler modele hiç ulaşmıyor" varsayımı yanlış, mekanizma var,
ama üç noktada dar.

## 2. Aynı hata neden tekrarlıyor — doğrulanmış nedenler

- **Anlamsal devralma eşiği kasıtlı dar.** Sadece neredeyse birebir
  aynı şikayetler otomatik devralınır. "Kargom gelmedi" düzeltmesi,
  farklı kelimelerle "paketim hâlâ elime ulaşmadı" yorumunu otomatik
  çevirmez — ancak örnek-gösterme katmanına tavsiye olarak girer,
  kararı yine model verir. En olası tek açıklama bu.
- **Örnek bütçesi doluyordu.** Aynı konuda 6'dan fazla geçmiş
  düzeltme varsa (yoğun/tekrarlayan bir şikayet, ör. bir kargo
  firmasıyla ilgili art arda düzeltmeler), 7. ve sonrası hiç
  gösterilmiyordu; sistem sessizce ilk 6'yla sınırlıydı.
- **Bir yorum grubu tek "ortalama" ile temsil ediliyor.** Toplu
  analiz 200 yorumu birden işler, en-yakın-örnek araması bu grubun
  ortalama anlamına göre yapılır, tek tek yoruma göre değil. Karışık
  konulu grupta ortalama hiçbir yorumu tam temsil etmez; bilinen bir
  sınır, bu turun kapsamı dışında (aşağıda M/L madde).
- **Otomatik devralma kalıcıdır.** Bir kez uygulandıysa o satır
  "Yeniden analiz et" ile bir daha gözden geçirilmez — yanlış
  devralma ancak yeni bir manuel düzeltmeyle düzelir. Eşiği gevşetmek
  riskli: yanlış-pozitifler kalıcılaşır. Bu yüzden eşiğe
  DOKUNULMADI (bkz. §3).
- **Model kusursuz değil.** Referans ölçümde (gold-500) duygu isabeti
  %97.0, kategori %90.8 — kalan pay kısmen modelin kendi hata payı,
  düzeltmeden bağımsız. Ayrı, daha büyük bir destek-bileti ağırlıklı
  ölçümde (9.902 satır) genel isabet %92.8 — FARKLI ölçümler, tek bir
  "güncel isabet" sayılmamalı.
- **Ölçüm aracı yoktu.** Değerlendirme betiği düzeltme örneklerini
  hiç kullanmıyordu — "örnek göstermek işe yarıyor mu" sorusunun
  sayısal cevabı yoktu. Bu turda kapatıldı (§3).

## 3. Bugün yapılan değişiklik

**A. Örnek bütçesi genişletildi.** Anlamsal en-yakın düzeltmelerden
prompt'a girebilecek üst sınır 6'dan **10'a** çıkarıldı. Toplam örnek
tavanı (12) DEĞİŞMEDİ — prompt maliyeti büyümedi, yalnız paylaşım
kaydı: yoğun konularda artık daha fazla geçmiş karar görünüyor, en az
2 slot her zaman en-güncel düzeltmelere ayrılmaya devam ediyor (yeni
bir düzeltme yoğun bir kümenin altında hiç görünmez olmasın diye).
Yalnız yoğun/tekrarlayan düzeltmesi olan kurumlarda etki yaratır;
anlamsal devralma eşiği (§2'deki riskli eşik) **bilinçli olarak
değiştirilmedi**. Değişiklik tek yerden yapıldı; toplu analiz, tekil
analiz ve yeniden-analiz akışlarının üçü de otomatik yansır.

**B. Ölçüm aracı düzeltme-farkındalı hale getirildi.** Değerlendirme
betiğine yeni bir seçenek eklendi: kurumun geçmiş düzeltmelerini
örnek olarak yükleyip referans setini bu haliyle koşturabiliyor
artık — "örnek göstermek isabeti artırıyor mu" sorusuna ilk kez
sayısal cevap alınabilir. **Sınır:** yalnız "en-güncel örnek
gösterme" katmanını test eder; referans satırları hiç "anlam
vektörüne" çevrilmediği için anlamsal-en-yakın ve anlamsal-devralma
katmanlarının etkisini ÖLÇMEZ — onlar ayrı, küçük bir referans seti
ister (aşağıda madde 2).

**C.** Testler ve kod içi açıklamalar eklendi: yeni bütçe davranışı,
eşiğin neden sabit kaldığı, ölçüm aracının sınırı.

## 4. Kalan öncelikli plan

1. **(XS, operasyon)** Sunucuda "anlam vektörü" özelliği açık mı,
   geçmiş düzeltmelerin ne kadarı vektörsüz kaldı — kontrol et.
   Vektörsüz düzeltme yalnız birebir eşleşmeye düşer, iki katmanı hiç
   kullanamaz; bulgulanırsa tek başına en büyük olası kazanım.
2. **(S, kod)** Gerçek düzeltme-yorum çiftlerinden küçük bir
   "genelleme" referans seti kur (bir düzeltme + onunla ilgili, hiç
   düzeltilmemiş kardeş yorum, elle etiketlenmiş). §3.B'nin
   ölçemediği iki katmanı ölçmenin TEK yolu — gold-500 bu amaçla
   kullanılamaz, hiçbir satırı bir düzeltmeden türememiş.
3. **(M, kod)** 200 yorumluk grubu küçük alt-gruplara bölüp her
   birine kendi "ortalama"sını verme — §2'deki 3. nedeni azaltır.
   Ek yapay-zeka çağrısı = ek maliyet; ölçülmeden uygulanmamalı.
4. **(M, kod, sadece veri — otomatik uygulama YOK)** Eşik sınırında
   kalan (devralınmayan ama yakın) çiftleri kaydeden bir
   "yakın-kaçırma" günlüğü — eşiği gevşetmeden ÖNCE gerçek veriye
   bakmayı sağlar; riskli eşik değişikliği yalnız bu veriyle
   tartışılmalı.
5. **(L, dondurulmuş çekirdek gerektirir)** Örnek aramayı grup
   ortalaması yerine yorum bazına indirmek — madde 3'ün maliyetsiz
   hâli, alt sistem (imga-core) şu an dondurulmuş olduğu için bu
   dalgada kapsam dışı.

## 5. Ölçüm tarifi

Her değişiklik gold-500'de koşturulur; sonuç duygu ≥0.965, kategori
≥0.900 altına düşmemeli (bugünkü .970/.908'in az altı tolerans).
Yeni "örnek göstermeyle" modu aynı sette açık/kapalı karşılaştırılır
— genellemenin gerçek etkisi yalnız madde 2'deki yeni referans
setiyle ölçülür, bu rapora o zaman gerçek sayılarla dönülecektir.
