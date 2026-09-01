"""Deterministik Türkçe veri kalitesi sezgiseli — migration 0042'nin
``reviews.quality_flag`` alanına yazılan 'informational' / 'meaningless'
değerlerinin TEK kaynağı.

2026-08-18 "büyük paket" WS2 — ölçüm sonucu tasarım kararı (bkz.
``docs/analysis/2026-08-18-buyuk-paket-plan.md`` DURUM notu): LLM
prompt'una bir "q" alanı eklemek gold4 kapısında belirsiz oranını
kötüleştirdi (.022 -> .044/.050/.058). Bunun yerine bu modül, batch
yazım yolunda (ve preview ön-doğrulamasında) metin üzerinde SAF
Python heuristiği çalıştırır — LLM'e hiç dokunmaz, sınıflandırma
prompt'unu etkilemez.

2026-08-18 adversarial inceleme (ampirik doğrulanmış): İLK tasarımın
iki mekanizması sistematik biçimde gerçek yorumları yanlış damgalıyordu.

  * "<=2 anlamlı sözcük -> meaningless" kuralı iki-üç kelimelik (ve
    Türkçede son derece yaygın) gerçek yorumları ('Beğenmedim', 'Hızlı
    kargo', 'kargo gecikmesi', 'eline sağlık') yakalıyordu. Bunu bir
    veto kelime listesiyle "kurtarmaya" çalışmak çekimli Türkçede asla
    kapanmaz (liste 'gecikme' içerir ama 'gecikmesi' içermez — her
    çekim biçimi için ayrı giriş gerekir). KURAL TAMAMEN KALDIRILDI:
    metin uzunluğu artık HİÇBİR kuralda tek başına sinyal değildir.
  * Kargo/gönderi durum kalıbı ('teslim edildi', 'kargoya verildi')
    TEK BAŞINA informational tetikliyordu — oysa bu kalıp bir şikâyet
    cümlesinin İÇİNDE de sık geçer ('Teslim edildi yazıyor, kutu boş
    çıktı', 'Kargoya verildi deniyor 5 gündür bekliyorum'). Durum
    kalıbı artık HİÇ bağımsız bir tetikleyici DEĞİL; yalnız şablon/
    otomasyon işareti (+ şikâyet yokluğu) informational üretir.

YENİ TASARIM İLKESİ — "yalnız KESİN çöp işaretlenir": her iki sınıf da
yalnız YAPISAL, yüksek-güvenilirlikli kalıplarla tetiklenir; "her
olası çekimi bir kelime listesinde yakala" yaklaşımı bırakılmıştır.
Şüpheli her durumda ``None`` döner ("geçerli satır" sayılır) — WS2'nin
varsayılan analitik filtresi (``include_flagged=False``) bayraklı
satırları rapor/heatmap/trendlerden düşürür, yani bir yanlış pozitif
gerçek bir şikâyeti sessizce gömer:

  * ``meaningless`` — SADECE:
      a) harf içermeyen metin (yalnız rakam/noktalama/sembol);
      b) tek başına telefon/sipariş-no/takip-no etiket+rakam kalıbı
         ('Sipariş no: 482910') ya da yalnız URL;
      c) TEK token olup selamlaşma/dolgu listesinde olan ('merhaba',
         'tamam', 'ok', 'test', 'asd' benzeri — bkz.
         ``_GREETING_FILLER_TOKENS``);
      d) TEK token, 4+ harf, sesli harf İÇERMEYEN — klavye karalaması
         ('sdfgh', 'qwrty'). Türkçede her hece bir sesli harf
         gerektirdiğinden gerçek bir kelime bu kalıba hiçbir zaman
         uymaz; bu yüzden eşik tahmini değil, kesin (sıfır sesli
         harf).
    İki-üç kelimelik hiçbir metin bu dört kalıbın hiçbirine girmez —
    kısa yorumlar artık meşru sayılır, uzunluk sinyal değildir.
  * ``informational`` — GEREKLİ KOŞUL (İKİSİ BİRDEN): (1) şablon/
    otomasyon işareti ('değerli müşterimiz', 'doğrulama kodu', no-
    reply başlığı, sistem digest'i vb. — bkz. ``_TEMPLATE_MARKERS``)
    VE (2) birinci-tekil iyelik/şikâyet işaretinin YOKLUĞU. İyelik/
    şikâyet kontrolü gövde-önek eşleşmesiyle yapılır
    (``token.startswith(stem)`` — 'kargom' gövdesi hem 'kargom' hem
    hâl ekli 'kargoma'/'kargomu' biçimlerini yakalar). Kargo/gönderi
    durum kalıbının kendisi ARTIK ayrıca kontrol edilmez — şablon
    işareti olmadan hiçbir zaman tek başına yeterli değildir.

Kalıplar bilinçli olarak modül sabitlerinde, tek bir global küme
olarak tutuluyor (kurum bazlı değil). Kurum-özel genişletme (örn.
belirli bir kurumun kendi otomatik bildirim şablonu) ileride bu
sabitlerin tenant-scoped bir overlay'e taşınmasıyla eklenebilir —
bugün kapsam dışı, tüm kurumlar aynı global kalıp kümesini paylaşır.
"""

from __future__ import annotations

import re
from typing import Final

from imga_core.text_utils import normalize_turkish

# ---------------------------------------------------------------------------
# informational — şablon/otomasyon işaretleri. GEREKLİ koşul: bu
# kalıplardan biri eşleşmeden informational hiçbir zaman tetiklenmez.
# ---------------------------------------------------------------------------

_TEMPLATE_MARKERS: Final[tuple[str, ...]] = (
    "değerli müşterimiz",
    "degerli musterimiz",
    "sayın müşterimiz",
    "sayin musterimiz",
    "bilgilendirme",
    "doğrulama kodu",
    "dogrulama kodu",
    "onay kodu",
    "no-reply",
    "noreply",
    "yanıtlamayınız",
    "yanitlamayiniz",
    "bu e-posta otomatik",
    "bu e posta otomatik",
    "bu mesaj otomatik",
    "otomatik olarak oluşturulmuştur",
    "otomatik olarak olusturulmustur",
    "otomatik bir bildirimdir",
    "abonelikten çık",
    "abonelikten cik",
    "unsubscribe",
    # 2026-08-18 keşif — eski kurum verisinde (Navlungo Test) rastlanan
    # analiz aracı digest e-postası imzası; müşteri yorumu olamayacak
    # kadar spesifik, tek başına yüksek-precision bir işaret.
    "happy number crunching",
)

# ---------------------------------------------------------------------------
# informational — birinci-tekil iyelik/şikâyet gövdeleri. Prefix-
# toleranslı eşleşir (token.startswith(stem)): 'kargom' gövdesi hâl
# ekli 'kargoma'/'kargomu' biçimlerini de yakalar. Hem Türkçe karakterli
# hem ASCII-katlanmış (klavye düzeni Türkçe olmayan kullanıcı girdisi)
# varyantlar bilinçli olarak birlikte tutulur.
# ---------------------------------------------------------------------------

_COMPLAINT_STEMS: Final[tuple[str, ...]] = (
    "kargom",
    "paketim",
    "siparişim",
    "siparisim",
    "ürünüm",
    "urunum",
    "yok",
    "boş",
    "bos",
    "değil",
    "degil",
    "gelmiyor",
    "bekliyorum",
)

# ---------------------------------------------------------------------------
# meaningless — düşük içerik heuristiği. Yalnız YAPISAL kalıplar;
# sözcük sayımı YOK.
# ---------------------------------------------------------------------------

# Tek-token selamlaşma/dolgu listesi — bunların dışındaki HİÇBİR
# tek/çok kelimelik metin salt uzunluk yüzünden meaningless sayılmaz.
_GREETING_FILLER_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "merhaba",
        "merhabalar",
        "selam",
        "selamlar",
        "tamam",
        "tamamdır",
        "tamamdir",
        "ok",
        "okay",
        "test",
        "deneme",
        "asd",
        "xxx",
    }
)

_TURKISH_VOWELS: Final[frozenset[str]] = frozenset("aeıioöuü")

# Sipariş/takip/telefon ETİKET kelimeleri — tek başına etiket+rakam
# kalıbını tanımak için (örn. 'Sipariş no: 482910').
_ORDER_PHONE_LABELS: Final[frozenset[str]] = frozenset(
    {
        "sipariş",
        "siparis",
        "takip",
        "tel",
        "telefon",
        "kod",
        "kodu",
        "no",
        "numara",
        "numarası",
        "numarasi",
    }
)

# Türkçe alfabenin yanına circumflex varyantları (â/î/û) eklenir —
# bazı gövdeler ('hâlâ' gibi) şapkalı harf taşıyor; eklenmezse
# tokenizer sözcüğü şapka noktasında bölerdi.
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-zçğıöşüâîû]+")
_URL_ONLY_RE: Final[re.Pattern[str]] = re.compile(r"^(https?://\S+|www\.\S+)$", re.IGNORECASE)
_DIGIT_OR_PUNCT_RE: Final[re.Pattern[str]] = re.compile(r"^[\d\s\-+().:/]*$")


def _matches_template_marker(normalized: str) -> bool:
    return any(phrase in normalized for phrase in _TEMPLATE_MARKERS)


def _has_first_person_complaint(normalized: str) -> bool:
    tokens = _WORD_RE.findall(normalized)
    return any(token.startswith(stem) for token in tokens for stem in _COMPLAINT_STEMS)


def _is_order_or_phone_pattern(normalized: str) -> bool:
    """Tek başına etiket+rakam kalıbı ('Sipariş no: 482910', 'Tel:
    0555 123 45 67'). Metindeki TÜM harf-token'lar etiket kelimesi
    olmalı VE etiketler çıkarıldıktan sonra geri kalan yalnız rakam/
    noktalama olmalı (en az bir rakamla) — aksi halde bu gerçek bir
    yorum cümlesidir ('Sipariş no 482910 hâlâ gelmedi' tokens'ında
    'gelmedi' etiket olmadığı için buradan False döner)."""
    tokens = _WORD_RE.findall(normalized)
    if not tokens or not all(t in _ORDER_PHONE_LABELS for t in tokens):
        return False
    remainder = _WORD_RE.sub("", normalized)
    return bool(_DIGIT_OR_PUNCT_RE.match(remainder)) and any(ch.isdigit() for ch in remainder)


def _is_keyboard_mash(token: str) -> bool:
    """Sesli harf içermeyen 4+ harflik tek token. Türkçede her hece
    bir sesli harf gerektirir, dolayısıyla gerçek bir kelime bu kalıba
    hiçbir zaman uymaz — eşik tahmini değil, kesin (sıfır sesli harf),
    bu yüzden precision-first ilkesiyle güvenlidir."""
    return len(token) >= 4 and not any(ch in _TURKISH_VOWELS for ch in token)


def _is_meaningless(normalized: str) -> bool:
    stripped = normalized.strip()
    if not stripped:
        return False
    if not any(ch.isalpha() for ch in stripped):
        # Yalnız rakam / telefon / sipariş-no / sembol.
        return True
    if _URL_ONLY_RE.match(stripped):
        return True
    if _is_order_or_phone_pattern(stripped):
        return True
    tokens = _WORD_RE.findall(stripped)
    if len(tokens) == 1:
        token = tokens[0]
        if token in _GREETING_FILLER_TOKENS:
            return True
        if _is_keyboard_mash(token):
            return True
    return False


def classify_data_quality(text: str) -> str | None:
    """Tek satırlık yorum metnini deterministik olarak sınıflandırır.

    Dönüş:
      * ``"informational"`` — şablon/otomasyon işareti VAR ve birinci-
        tekil iyelik/şikâyet işareti YOK.
      * ``"meaningless"`` — içerik neredeyse yok (harf içermeyen /
        yalnız URL / yalnız etiket+rakam / tek token selamlaşma-dolgu
        ya da sesli harfsiz klavye karalaması).
      * ``None`` — geçerli satır (şüphede varsayılan; boş metin de
        buraya düşer — boş metnin ayrı bir yazım yolu var, bu
        fonksiyon onu çağırmaz).

    Sıra: önce informational (daha spesifik — şablon işareti + şikâyet
    yokluğu ikisi birden gerekir), sonra meaningless (yapısal düşük-
    içerik kalıpları). İki kontrol birbirini dışlar: bir metin ikisine
    birden uyamaz (informational şablon dili taşır, meaningless
    tanımı gereği neredeyse içeriksizdir).
    """
    if not text:
        return None
    normalized = normalize_turkish(text).strip()
    if not normalized:
        return None

    if _matches_template_marker(normalized) and not _has_first_person_complaint(normalized):
        return "informational"

    if _is_meaningless(normalized):
        return "meaningless"

    return None


# ---------------------------------------------------------------------------
# content_type ('question' | 'suggestion' | 'thanks' | 'request' |
# 'escalation') — migration 0049 (question) + 0050 (diğer dördü).
# classify_data_quality'nin YANINDA, ama ondan BAĞIMSIZ bir sezgisel:
# dönüşü ``reviews.quality_flag`` DEĞİL ``reviews.content_type``'a
# yazılır (bkz. modül ve model docstring'leri) — bir NEGATİF şikayetin
# soru biçiminde yazılması ("Kargom nerede, ilgilenir misiniz?") hâlâ
# 'question'dur VE analitikte KALMALIDIR; quality_flag'in aksine bu bir
# "düşük kalite" işareti değil, metnin YAPISAL biçimidir.
# classify_data_quality'nin ilk tasarımındaki LLM "q" alanı denemesi
# ölçülüp reddedildiği (2026-08-18, gold4 kapı regresyonu) için burada
# da aynı ilke geçerli: SAF yapısal Türkçe heuristik, LLM'e hiç
# dokunmadan.
#
# ÖNCELİK (2026-09-01, migration 0050) — bir satır birden çok kalıba
# birden uyabilir (ör. "İade istiyorum, yoksa tüketici hakem heyetine
# gideceğim" hem request hem escalation kalıbına uyar); RİSK-ÖNCELİKLİ
# sıra ilk eşleşeni kazandırır, detect_content_type bu sırayla dener:
#
#     escalation > request > question > suggestion > thanks
#
# Gerekçe (risk azalan sırada): escalation (resmi/hukuki eskalasyon
# tehdidi) kaçırılırsa kurum hazırlıksız yakalanıp resmi bir başvuruyla
# karşılaşabilir — en yüksek risk. request (somut eylem talebi — iade/
# iptal/geri ödeme/geri arama) SLA'ya bağlıdır, cevapsız kalırsa
# müşteri kaybı riski taşır. question nötr bir bilgi talebidir — ne
# request kadar aksiyoner ne escalation kadar riskli. suggestion ürün
# geri bildirimidir, aksiyon gerektirmez. thanks en düşük risk —
# kaçırılsa bile operasyonel sonucu yoktur, yalnız memnuniyet sinyali.
#
# question kuralı (YÜKSEK-GÜVENİLİRLİK, değişmedi): (a) '?' VARSA VE bir
# soru işareti taşıyorsa (soru zamiri/zarfı YA DA soru eki 'mi/mı/mu/mü'
# herhangi bir token'da) YA DA metin '?' ile bitiyorsa; (b) '?' YOKSA
# ama SON token çıplak soru eki ise ('mi'...'mısınız' gibi ekli
# biçimler dahil). '?' cümle içinde gelişigüzel geçip hiçbir soru
# işareti taşımıyorsa (ör. "Fiyat/performans? bence harika") KESİNLİKLE
# question işaretlenmez — ama alt sıradaki suggestion/thanks kalıpları
# hâlâ denenir (bkz. ``_is_question``).
#
# escalation/request/suggestion/thanks ortak eşleştirme deseni: her
# kalıp bir kelime tuple'ı (bkz. ``_phrase_matches``), ARDIŞIK token'lar
# üzerinde her token'ın karşılık gelen kalıp kelimesiyle BAŞLAMASI
# (prefix-tolerant) şartıyla aranır — ``_has_first_person_complaint``'
# teki ``token.startswith(stem)`` deyiminin çok-kelimeli genellemesi.
# Bu hem çekim toleransı sağlar ("dava aç" kalıbı "dava açacağım"ı da
# yakalar) hem de eşleşmeyi HER ZAMAN bir token BAŞINA çapalar — ham
# metin üzerinde `phrase in normalized` aramak yapmazdı bunu: "mi"
# token tuzağıyla (yukarıdaki ``_QUESTION_PARTICLE_RE.fullmatch``
# gerekçesiyle aynı hata sınıfı) çok-kelimeli kalıplara bulaşmasın diye
# token bazlı arandı.
# ---------------------------------------------------------------------------

_INTERROGATIVE_PRONOUNS: Final[frozenset[str]] = frozenset(
    {
        "ne",
        "nasıl",
        "nasil",
        "neden",
        "niye",
        "nerede",
        "nereden",
        "kaç",
        "kac",
        "hangi",
        "kim",
    }
)

# Soru eki 'mi' — ünlü uyumuyla dört biçim (mi/mı/mu/mü), yalın ya da
# şahıs/zaman ekli (miyim, mısınız, miydi, muymuş, midir...). Türkçe
# yazım kuralı gereği bu ek fiile BİTİŞMEZ, ayrı yazılır — tokenizer'da
# (``_WORD_RE``) her zaman kendi başına bir token olarak görünür. Regex
# TAM token eşleşmesi arar (``fullmatch``): 'mı' ile BAŞLAYIP farklı bir
# ekle DEVAM EDEN gerçek sözcükleri ('mısır'=corn, 'resmi'=official,
# 'mide'=stomach, 'milyon') yanlış yakalamaz — o sözcüklerin ikinci
# hecesi aşağıdaki ek listesinde YOKTUR.
_QUESTION_PARTICLE_RE: Final[re.Pattern[str]] = re.compile(
    r"mi(?:yim|sin|yiz|siniz|ydim|ydin|ydi|ydik|ydiniz|ydiler|"
    r"ymişim|ymişsin|ymiş|ymişiz|ymişsiniz|ymişler|dir)?"
    r"|mı(?:yım|sın|yız|sınız|ydım|ydın|ydı|ydık|ydınız|ydılar|"
    r"ymışım|ymışsın|ymış|ymışız|ymışsınız|ymışlar|dır)?"
    r"|mu(?:yum|sun|yuz|sunuz|ydum|ydun|ydu|yduk|ydunuz|ydular|"
    r"ymuşum|ymuşsun|ymuş|ymuşuz|ymuşsunuz|ymuşlar|dur)?"
    r"|mü(?:yüm|sün|yüz|sünüz|ydüm|ydün|ydü|ydük|ydünüz|ydüler|"
    r"ymüşüm|ymüşsün|ymüş|ymüşüz|ymüşsünüz|ymüşler|dür)?"
)


def _has_interrogative_signal(tokens: list[str]) -> bool:
    return any(
        token in _INTERROGATIVE_PRONOUNS or _QUESTION_PARTICLE_RE.fullmatch(token)
        for token in tokens
    )


def _is_question(normalized: str, tokens: list[str]) -> bool:
    """question kuralı (a)+(b), ``detect_content_type``'ın docstring'inde
    açıklanır. Ayrı bir predicate olarak tutulur (eskiden fonksiyonun
    kendisiydi) çünkü artık soru-DEĞİL sonucu pipeline'ı durdurmuyor —
    alt sıradaki suggestion/thanks kalıpları hâlâ denenmeli (ör.
    "Fiyat/performans? bence harika" — soru değil ama suggestion/thanks
    kontrolüne düşmeye devam etmeli, sırf bu örnekte ikisi de
    eşleşmediği için None kalıyor)."""
    if "?" in normalized:
        return normalized.endswith("?") or _has_interrogative_signal(tokens)
    return bool(tokens) and _QUESTION_PARTICLE_RE.fullmatch(tokens[-1]) is not None


def _phrase_matches(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    """``phrase``'in ARDIŞIK token'lar üzerinde, her token'ın karşılık
    gelen kalıp kelimesiyle BAŞLAMASI şartıyla eşleşip eşleşmediği
    (prefix-tolerant contiguous match) — bkz. yukarıdaki bölüm başlığı
    yorumu."""
    span = len(phrase)
    return any(
        all(tokens[i + j].startswith(phrase[j]) for j in range(span))
        for i in range(len(tokens) - span + 1)
    )


def _matches_any_phrase(tokens: list[str], phrases: tuple[tuple[str, ...], ...]) -> bool:
    return any(_phrase_matches(tokens, phrase) for phrase in phrases)


# --- escalation — resmi/hukuki eskalasyon TEHDİDİ/duyurusu ----------------

_ESCALATION_PHRASES: Final[tuple[tuple[str, ...], ...]] = (
    ("tüketici", "hakem"),
    ("hakem", "heyeti"),
    ("tüketici", "mahkemesi"),
    ("tüketici", "hakları"),
    ("dava", "aç"),
    ("dava", "edeceğim"),
    ("mahkeme",),
    ("savcılığa",),
    ("savcılık",),
    ("avukat",),
    ("cimer",),
    ("şikayetvar",),
    ("sikayetvar",),
    ("btk",),
    ("ticaret", "bakanlığı"),
    ("yasal", "yollara"),
    ("yasal", "işlem"),
    ("hukuki", "işlem"),
    ("ihtar",),
)

# --- request — somut bir eylem talebi (iade/iptal/geri ödeme/geri arama/
# bilgi-dönüş) --------------------------------------------------------------

_REQUEST_PHRASES: Final[tuple[tuple[str, ...], ...]] = (
    ("talep", "ediyorum"),
    ("talep", "ederim"),
    ("rica", "ediyorum"),
    ("rica", "ederim"),
    ("rica", "olunur"),
    ("geri", "arayın"),
    ("geri", "arar", "mısınız"),
    ("dönüş", "yapın"),
    ("dönüş", "bekliyorum"),
    ("bilgi", "verin"),
    ("iade", "istiyorum"),
    ("iadesini", "istiyorum"),
    ("iptal", "istiyorum"),
    ("iptalini", "istiyorum"),
    ("geri", "ödeme", "istiyorum"),
    ("paramı", "istiyorum"),
    ("paramın", "iadesini"),
    ("çözüm", "bekliyorum"),
    ("acilen", "ilgilenin"),
)

# Bare "istiyorum" HİÇBİR ZAMAN tek başına request tetiklemez ("memnun
# kalmak istiyorum" bir talep değil) — yukarıdaki liste yalnız SOMUT bir
# eylem kökünden ("iade", "iptal", "geri ödeme", "paramı"...) SONRA
# gelen "istiyorum"u tanır; bare "istiyorum" bu yüzden listede YOK.
#
# "lütfen" + aşağıdaki eylemlerden biri de aynı somut-eylem-talebi
# şartını karşılar (nazik istek biçimi — "lütfen" tek başına yeterli
# değil, bir eylem fiiliyle BİRLİKTE gerekir).
_REQUEST_LUTFEN_TRIGGERS: Final[tuple[tuple[str, ...], ...]] = (
    ("arayın",),
    ("dönüş", "yapın"),
    ("düzeltin",),
    ("iletişime", "geçin"),
    ("çözün",),
    ("gönderin",),
    ("iade", "edin"),
    ("iptal", "edin"),
    ("bilgilendirin",),
    ("ilgilenin",),
)

# --- suggestion — ürün/hizmet önerisi ---------------------------------------

_SUGGESTION_PHRASES: Final[tuple[tuple[str, ...], ...]] = (
    ("keşke",),
    ("olsa", "iyi", "olur"),
    ("olsa", "güzel", "olur"),
    ("olsa", "daha", "iyi"),
    ("olursa", "iyi", "olur"),
    ("öneririm",),
    ("önerim",),
    ("tavsiyem",),
    ("eklenmeli",),
    ("geliştirilmeli",),
    ("iyileştirilmeli",),
    ("düzeltilmeli",),
    ("yapılmalı",),
    ("olmalı",),
    ("ekleseniz",),
    ("yapsanız",),
    ("getirseniz",),
    ("eklenirse",),
    ("eklerseniz",),
)

# "tavsiye ederim" / "herkese tavsiye ederim" BİLİNÇLİ OLARAK yukarıdaki
# listede YOK: bu bir ÖVGÜ cümlesidir, öneri değil. "tavsiyem" (iyelik
# ekli isim biçimi, "önerim" anlamında) farklı bir kelime — çıplak kök
# "tavsiye" hiçbir kalıba PREFIX olarak uymadığı için (bkz.
# ``_phrase_matches``'in token.startswith yönü: aranan token, kalıp
# kelimesinden KISA olamaz) "tavsiye ederim" hiçbir suggestion kalıbını
# tetiklemez.
_SUGGESTION_MODAL_SUFFIXES: Final[tuple[str, ...]] = (
    "malı",
    "meli",
    "malısınız",
    "melisiniz",
)


def _has_bence_suggestion(tokens: list[str]) -> bool:
    """ "bence ... olmalı" kalıbı — "bence" token'ı VE cümlede -malı/
    -meli ekiyle biten herhangi bir token bir arada. Sabit listedeki
    fiillerin (eklenmeli, düzeltilmeli...) DIŞINDA kalan, önceden tahmin
    edilemeyen fiiller için genel bir yakalayıcı (ör. "Bence teslimat
    süresi azaltılmalı") — "bence" şartı olmadan -malı/-meli eki TEK
    BAŞINA aşırı geniş olurdu (Türkçede gereklilik kipi genel amaçlı
    kullanılır, öneriyle sınırlı değildir)."""
    if "bence" not in tokens:
        return False
    return any(token.endswith(suffix) for token in tokens for suffix in _SUGGESTION_MODAL_SUFFIXES)


# --- thanks — yalnız minnettarlık ifadesi (genel pozitif duygu DEĞİL) ------

_THANKS_PHRASES: Final[tuple[tuple[str, ...], ...]] = (
    ("teşekkür",),
    ("teşekkürler",),
    ("teşekkür", "ederim"),
    ("teşekkürler", "ederim"),
    ("tesekkur",),
    ("tesekkurler",),
    ("sağ", "olun"),
    ("sağolun",),
    ("sagolun",),
    ("sağ", "ol"),
    ("ellerinize", "sağlık"),
    ("minnettarım",),
    ("çok", "teşekkür"),
)

# "harika"/"mükemmel" gibi genel pozitif duygu kelimeleri BİLİNÇLİ
# OLARAK yukarıdaki listede YOK — bunlar memnuniyet ifade eder,
# minnettarlık değil; sentiment zaten ayrı bir kolonda (sentiment_label)
# tutuluyor, thanks onunla karıştırılmaz.


def detect_content_type(text: str) -> str | None:
    """Tek satırlık yorum metninin YAPISAL biçimini tespit eder.

    Dönüş — RİSK-ÖNCELİKLİ sırayla denenir, ilk eşleşen kazanır (bkz.
    yukarıdaki bölüm başlığı yorumu "ÖNCELİK" için tam gerekçe):

      1. ``"escalation"`` — resmi/hukuki eskalasyon TEHDİDİ/duyurusu
         (tüketici hakem heyeti, mahkeme/dava, avukat, savcılık, CİMER,
         şikayetvar, BTK, Ticaret Bakanlığı, "yasal yollara" vb. — bkz.
         ``_ESCALATION_PHRASES``). EN YÜKSEK risk: kaçırılırsa kurum
         hazırlıksız yakalanır.
      2. ``"request"`` — somut bir eylem talebi (iade/iptal/geri ödeme/
         geri arama/bilgi-dönüş — bkz. ``_REQUEST_PHRASES`` +
         "lütfen" + eylem fiili kombinasyonu). Bare "istiyorum" TEK
         BAŞINA asla tetiklemez ("memnun kalmak istiyorum" request
         DEĞİL) — yalnız somut bir eylem kökünden sonra gelen
         "istiyorum" sayılır.
      3. ``"question"`` — metin bir soru olarak yazılmış (bkz.
         ``_is_question`` — aşağıdaki iki kural, DEĞİŞMEDİ):

         (a) Metinde '?' VARSA VE (bir soru zamiri/zarfı — ``ne``,
             ``nasıl``, ``neden``, ``niye``, ``nerede``, ``nereden``,
             ``kaç``, ``hangi``, ``kim`` — ya da soru eki 'mi/mı/mu/mü'
             herhangi bir token'da geçiyorsa YA DA metin '?' ile
             BİTİYORSA) -> 'question'. '?' cümle içinde gelişigüzel
             geçip hiçbir soru işareti taşımıyorsa VE metin '?' ile
             bitmiyorsa question İŞARETLENMEZ (ama alt sıradaki
             suggestion/thanks kalıpları hâlâ denenir) — ör.
             "Fiyat/performans? bence harika" burada '?' salt vurgu/
             duraklama işareti, cümle bir soru DEĞİL.
         (b) Metinde '?' YOKSA ama SON token çıplak soru eki ('mi'...
             'mısınız' gibi ekli biçimler dahil) ise -> 'question'
             ("İade edebilir miyim" gibi soru işaretsiz yazılmış
             gerçek sorular).
      4. ``"suggestion"`` — bir öneri/iyileştirme talebi (keşke,
         öneririm, X eklenmeli/olmalı, "bence X azaltılmalı" gibi —
         bkz. ``_SUGGESTION_PHRASES`` + ``_has_bence_suggestion``).
         "tavsiye ederim" BİLİNÇLİ OLARAK bu kapsamda DEĞİL (övgü,
         öneri değil — bkz. ``_SUGGESTION_PHRASES`` üstündeki not).
      5. ``"thanks"`` — yalnız minnettarlık ifadesi (teşekkür/sağ olun/
         ellerinize sağlık vb. — bkz. ``_THANKS_PHRASES``). Genel
         pozitif duygu kelimeleri ("harika") bu kapsamda DEĞİL.
      * ``None`` — hiçbir kalıp eşleşmedi (şüphede varsayılan; boş
        metin de buraya düşer).

    ORTOGONAL not: bu fonksiyon ``classify_data_quality``'den TAMAMEN
    bağımsızdır ve onun sonucunu hiçbir şekilde etkilemez/etkilenmez —
    bir şikayetin soru biçiminde yazılması onu 'question' yapar ama
    'informational'/'meaningless' YAPMAZ; aynı ortogonallik dört yeni
    değer için de geçerli.
    """
    if not text:
        return None
    normalized = normalize_turkish(text).strip()
    if not normalized:
        return None

    tokens = _WORD_RE.findall(normalized)

    if _matches_any_phrase(tokens, _ESCALATION_PHRASES):
        return "escalation"

    if _matches_any_phrase(tokens, _REQUEST_PHRASES) or (
        "lütfen" in tokens and _matches_any_phrase(tokens, _REQUEST_LUTFEN_TRIGGERS)
    ):
        return "request"

    if _is_question(normalized, tokens):
        return "question"

    if _matches_any_phrase(tokens, _SUGGESTION_PHRASES) or _has_bence_suggestion(tokens):
        return "suggestion"

    if _matches_any_phrase(tokens, _THANKS_PHRASES):
        return "thanks"

    return None


__all__ = ["classify_data_quality", "detect_content_type"]
