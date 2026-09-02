"""twitterapi.io üzerinden tweet çekimi — "Twitter'dan Çek" entegrasyonu.

imga.ai pazarlama sitesindeki trial akışının (site repo'su
``src/lib/twitter.ts``) sunucu tarafı karşılığı: advanced_search
sayfalı çekim + temizle/dedupe. Anahtar kelime çıkarımı (Gemini) bilerek
yok — kullanıcı arama terimini kendisi verir; sorgu deterministik kalır.

2026-08-26 — alaka filtresi. X araması terimi gönderi metninin yanı sıra
YAZARIN ADINDA da eşler: "karaca" sorgusu Karaca soyadlı herkesin
gönderisini getirdi (250'de ~15 marka yorumu). Kural: terim(lerden
biri) gönderinin HAM metninde geçmeli ya da gönderi resmi hesaba
yazılmış olmalı; aksi halde elenir (``filtered_out`` sayılır).

2026-09-02 — KVKK: source_url anonimleştirme. Prodüksiyonda mevcut 677
Twitter satırının TAMAMI ``reviews.source_url`` alanında yazar hesap
adını taşıyor bulundu (``https://x.com/<handle>/status/<id>``) — "yazar
kimliği hiçbir yerde kalıcı yazılmaz" kuralı ihlal ediliyordu; URL
içindeki hesap adı da kimliktir. ``tweet_url_from_item`` bu yüzden ARTIK
HER ZAMAN hesap adı içermeyen kanonik biçimi
(``https://x.com/i/web/status/{id}``) üretir — ``item["url"]`` alanı
doğrudan döndürülmez, yalnız id çıkarımı için okunur. Geçmiş satırlar
``scripts/sql/2026-09-02-twitter-source-url-anonymize.sql`` ile tek
seferlik geri dönüştürülür.

2026-09-02 — #işbirliği/#reklam ön-filtresi + arka plan ilerlemesi.
İşbirliği/reklam etiketli gönderiler (``is_collab_hashtag``) marka
alaka hakemine hiç gitmeden elenir: bunlar zaten "marka hakkında"
ama müşteri sesi değil (sponsorlu içerik), hakem parasını harcamaya
değmez. Aynı değişiklikle ``fetch_tweets`` isteğe bağlı bir ``on_page``
kancası aldı — çekim artık uzun sürebilen bir arka plan işinde
(``workers/twitter_fetch.py``) koşuyor, kancasız hâliyle çağıran taraf
tamamlanana kadar hiçbir ilerleme göremiyordu.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from imga_api.services.smart_parser.base import normalize_header

_logger = logging.getLogger("imga-api.services.twitter_import")

SEARCH_URL = "https://api.twitterapi.io/twitter/tweet/advanced_search"
# twitterapi.io sayfa başına ~20 tweet döner; 1000 hedefi için 80 sayfa
# üst sınır yeterli (pratikte sorgu çok daha erken tükenir).
MAX_PAGES = 80
PAGE_DELAY_SECONDS = 0.3
MIN_TEXT_LENGTH = 5
MIN_TERM_LENGTH = 2

_URL_RE = re.compile(r"https?://\S+")
_LEADING_MENTIONS_RE = re.compile(r"^(?:@\w+\s+)+")
_WS_RE = re.compile(r"\s+")
# item["url"]'den id çıkarımı — KVKK: yalnız sayısal id alınır, hesap
# adı (<anything> parçası) hiçbir zaman okunmaz/taşınmaz.
_STATUS_ID_RE = re.compile(r"(?:x|twitter)\.com/[^/]+/status/(\d+)")

# twitterapi.io tweet'in atılma anını Twitter'ın klasik biçiminde
# döner ("Tue Dec 10 07:00:30 +0000 2024"). ISO da görülebiliyor, o
# yüzden iki deneme.
_TWITTER_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"


class TwitterFetchError(Exception):
    """twitterapi.io'ya ilk sayfada bile ulaşılamadı (ağ / auth / kota)."""


@dataclass(frozen=True, slots=True)
class TwitterTweet:
    """Tek tweet: temizlenmiş metin + atılma anı + kalıcı bağlantı.

    ``created_at`` None ise tarih çözülemedi — batch pipeline yorumun
    kendi tarihi olarak ingest anına düşer (yorum kaybolmaz). ``url``
    gönderinin x.com bağlantısı (KVKK: her zaman hesap adı içermeyen
    ``x.com/i/web/status/{id}`` biçimi — bkz. ``tweet_url_from_item``);
    arşivde "Tweeti aç" düğmesi buna gider (bağlam olmadan alaka
    anlaşılmıyordu)."""

    text: str
    created_at: datetime | None
    url: str | None = None
    # Mention/URL atılmamış ham metin — yalnız AI alaka hakemi için
    # (bkz. twitter_brand_service); CSV'ye / arşive İNMEZ.
    raw_text: str = ""
    # Migration 0049 — etkileşim sayaçları (twitterapi.io: likeCount/
    # retweetCount/replyCount/viewCount). Alan yoksa ya da sayıya
    # çevrilemiyorsa None. KVKK: yazar kimliği (userName/name) buraya
    # BİLEREK taşınmaz — bkz. modül docstring'i, fetch_tweets bu
    # alanları yalnız alaka filtresi için geçici okur, hiçbir yerde
    # kalıcı yazmaz.
    like_count: int | None = None
    retweet_count: int | None = None
    reply_count: int | None = None
    view_count: int | None = None


# X gelişmiş arama sorgu uzunluğu ~512 karakterle sınırlı; plan
# terimleri bunu aşarsa negatifler sondan düşürülür.
MAX_QUERY_LENGTH = 500


@dataclass(frozen=True, slots=True)
class TwitterFetchResult:
    tweets: list[TwitterTweet]
    fetched_total: int
    pages: int
    # True → sayfalama bitti; istenen sayıya ulaşılamadıysa X'te bu
    # sorgu için daha fazla Türkçe sonuç yok demektir.
    exhausted: bool
    # Alaka filtresinin elediği gönderi sayısı (terim metinde yok ve
    # resmi hesaba yazılmamış). Kullanıcıya "neden az geldi" bilgisi.
    filtered_out: int = 0
    # #işbirliği/#reklam/#sponsor/#sponsorlu etiketli, alaka hakemine
    # hiç gitmeden elenen gönderi sayısı (bkz. ``is_collab_hashtag``).
    excluded_collab: int = 0
    # Tutulan gönderiler arasında en eski/en yeni atılma anı — "ne
    # kadar geriye gidildi" sorusunun cevabı (arka plan ilerlemesi
    # bunu ``on_page`` üzerinden zaten anlık gösterir; burada
    # çekimin TAMAMI bittiğindeki son değer).
    oldest_tweet_at: datetime | None = None
    newest_tweet_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TwitterFetchProgress:
    """``fetch_tweets``'in ``on_page`` kancasına verdiği anlık durum —
    her sayfa sonunda bir kez, çekimin tamamı bitene kadar arka plan
    işinin ilerleme yayınlayabilmesi için (bkz. ``workers/twitter_fetch.py``).
    """

    pages_done: int
    fetched_total: int
    tweets_found: int
    filtered_out: int
    excluded_collab: int
    oldest_tweet_at: datetime | None
    newest_tweet_at: datetime | None


@dataclass(frozen=True, slots=True)
class SearchTerms:
    """Kullanıcının terim alanından çözülen sorgu parçaları.

    Alan virgülle birden çok terim alır; ``-`` ile başlayanlar hariç
    tutma terimidir: ``karaca, -cem karaca, -hidayet karaca``."""

    positive: tuple[str, ...]
    negative: tuple[str, ...]


def parse_tweet_created_at(raw: object) -> datetime | None:
    """Tweet zaman damgasını UTC datetime'a çevir; olmuyorsa None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _TWITTER_DATE_FORMAT).astimezone(UTC)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_search_terms(raw: str) -> SearchTerms:
    """Virgülle ayrılmış terim alanını pozitif/negatif listelere böl.

    Tırnaklar atılır, ``MIN_TERM_LENGTH`` altındaki parçalar yok
    sayılır, sıra ve tekrar korunmaz (dedupe). Hiç pozitif terim
    kalmazsa ``positive`` boş döner — route 422 üretir."""
    positive: list[str] = []
    negative: list[str] = []
    for chunk in raw.split(","):
        term = _WS_RE.sub(" ", chunk.replace('"', "")).strip()
        is_negative = term.startswith("-")
        if is_negative:
            term = term[1:].strip()
        if len(term) < MIN_TERM_LENGTH:
            continue
        bucket = negative if is_negative else positive
        if term not in bucket:
            bucket.append(term)
    return SearchTerms(positive=tuple(positive), negative=tuple(negative))


def _quote_term(term: str) -> str:
    # @hesap / #etiket X operatörüdür, tırnaklanmaz.
    if term.startswith(("@", "#")) and " " not in term:
        return term
    return f'"{term}"'


def build_search_query(term: str, exclude_handle: str | None) -> str:
    """Site ile aynı sorgu dili: terim tırnaklı, Türkçe, RT'siz; resmi
    hesap verilmişse onun kendi paylaşımları hariç (müşteri sesi değil).

    Birden çok pozitif terim OR grubuna alınır, negatif terimler ``-``
    ile düşülür. Tek terim → eski çıktıyla birebir aynı."""
    terms = parse_search_terms(term)
    handle = (exclude_handle or "").lstrip("@").strip()
    positives = [_quote_term(t) for t in terms.positive] or [_quote_term(term.strip())]
    head = positives[0] if len(positives) == 1 else "(" + " OR ".join(positives) + ")"
    negatives = [f"-{_quote_term(t)}" for t in terms.negative]
    tail = [f"-from:{handle}"] if handle else []
    tail.append("lang:tr -filter:retweets")

    def _join(negs: list[str]) -> str:
        return " ".join([head, *negs, *tail])

    query = _join(negatives)
    while len(query) > MAX_QUERY_LENGTH and negatives:
        negatives.pop()
        query = _join(negatives)
    return query


def clean_tweet_text(raw: str) -> str:
    """URL'leri ve baştaki @mention zincirini at, boşlukları normalize et."""
    text = _URL_RE.sub("", raw)
    text = _LEADING_MENTIONS_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def tweet_url_from_item(item: dict[str, object]) -> str | None:
    """twitterapi.io öğesinden KVKK-uyumlu kalıcı bağlantı üretir.

    Dönen bağlantı HER ZAMAN hesap adı içermeyen kanonik biçimdir:
    ``https://x.com/i/web/status/{id}``. ``item["url"]`` (varsa
    ``https://x.com/<handle>/status/<id>``) hiçbir zaman doğrudan
    döndürülmez — yazar hesap adı da kimliktir. Önce ``id`` alanından
    sayısal id denenir; o yoksa/sayısal değilse ``url``'den regex ile
    id çıkarılır. İkisi de başarısızsa None (bağlantısız satır olarak
    işlenir)."""
    tweet_id = item.get("id")
    if tweet_id is not None:
        candidate = str(tweet_id).strip()
        if candidate.isdigit():
            return f"https://x.com/i/web/status/{candidate}"
    url = item.get("url")
    if isinstance(url, str):
        match = _STATUS_ID_RE.search(url)
        if match:
            return f"https://x.com/i/web/status/{match.group(1)}"
    return None


def _coerce_engagement_count(raw: object) -> int | None:
    """twitterapi.io sayaç alanını (likeCount vb.) tolerant biçimde
    int'e çevirir; alan yok / negatif / sayıya çevrilemiyor -> None."""
    if raw is None:
        return None
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


_HASHTAG_RE = re.compile(r"#(\w+)")
# Türkçe-aware fold sonrası (bkz. normalize_header) tam eşleşme —
# startswith DEĞİL: "#reklamsız" ("reklam yok" anlamında, markayla
# ilgili meşru bir gönderi olabilir) "reklam" ile başlar ama
# normalize_header sonrası "reklamsiz" != "reklam", yanlış elenmez.
# "iş birliği" iki ayrı kelime olarak bir hashtag'e HİÇ giremez
# (``#\w+`` boşluk üzerinden asla eşleşmez) — bilerek ayrı bir
# ifade-arama kuralı eklenmedi; sıradan "iş birliği yaptık" gibi
# markayla ilgili cümlelerde yanlış pozitif üretmemesi için.
_COLLAB_HASHTAG_STEMS = frozenset({"isbirligi", "reklam", "sponsor", "sponsorlu"})


def is_collab_hashtag(raw_text: str) -> bool:
    """Gönderi #işbirliği/#reklam/#sponsor/#sponsorlu etiketlerinden
    birini taşıyor mu (büyük/küçük harf, Türkçe İ/ı ve aksan
    duyarsız). Böyle gönderiler sponsorlu içeriktir — marka hakkında
    olsa bile gerçek müşteri sesi değildir, alaka hakemine hiç
    gitmeden elenir (bkz. ``fetch_tweets``, ``excluded_collab``)."""
    for match in _HASHTAG_RE.finditer(raw_text):
        if normalize_header(match.group(1)) in _COLLAB_HASHTAG_STEMS:
            return True
    return False


def tweet_matches_terms(
    raw_text: str,
    terms: SearchTerms,
    official_handle: str | None,
    *,
    in_reply_to: str | None = None,
) -> bool:
    """Alaka kuralı: pozitif terimlerden biri HAM metinde (mention'lar
    atılmadan önce) geçiyor ya da gönderi resmi hesaba yazılmış
    (``@hesap`` metinde ya da yanıt hedefi). Karşılaştırma büyük/küçük
    harf, Türkçe İ/ı ve aksan duyarsız düz alt-dizi eşleşmesidir —
    "Karaca'nın" da "#karacahome" da eşleşir."""
    folded = normalize_header(raw_text)
    for term in terms.positive:
        if normalize_header(term) in folded:
            return True
    handle = normalize_header((official_handle or "").lstrip("@"))
    if handle:
        if f"@{handle}" in folded:
            return True
        if in_reply_to and normalize_header(in_reply_to.lstrip("@")) == handle:
            return True
    return False


async def fetch_tweets(
    *,
    api_key: str,
    term: str,
    count: int,
    exclude_handle: str | None = None,
    on_page: Callable[[TwitterFetchProgress], Awaitable[None]] | None = None,
) -> TwitterFetchResult:
    """En yeni tweetlerden ``count`` temiz metin + tarih + bağlantı topla.

    İlk sayfa hatası ``TwitterFetchError`` olarak yükselir; sonraki
    sayfalardaki hatalar eldeki kısmi sonuçla sessizce döner (yarım
    veri, sıfır veriden iyidir — batch pipeline gerisini halleder).
    Sırayla iki filtre uygulanır: önce ``is_collab_hashtag``
    (``excluded_collab``'a sayılır — işbirlikli/sponsorlu bir gönderi
    marka hakkında olsa bile müşteri sesi değildir, alaka hakemine hiç
    gitmez), sonra ``tweet_matches_terms`` (``filtered_out``). Bu sıra
    bilerek böyle: sponsor etiketli AMA konu dışı bir gönderi
    "sponsorlu" olarak sayılır — kullanıcıya daha eyleme dönüştürülebilir
    sinyal budur.

    ``on_page`` verilirse her sayfa sonunda (son sayfa dahil, uyku
    öncesi) bir kez çağrılır — arka plan işinin ilerlemeyi Redis'e
    yazabilmesi içindir (bkz. ``workers/twitter_fetch.py``). Kanca bir
    istisna fırlatırsa çekim DURMAZ: loglanır ve yutulur — bu yalnız
    bir UI ipucu, hiçbir zaman çekimi engellememeli.
    """
    query = build_search_query(term, exclude_handle)
    terms = parse_search_terms(term)
    if not terms.positive:
        terms = SearchTerms(positive=(term.strip(),), negative=())
    tweets: list[TwitterTweet] = []
    seen: set[str] = set()
    fetched_total = 0
    filtered_out = 0
    excluded_collab = 0
    pages = 0
    cursor = ""
    exhausted = False
    oldest_at: datetime | None = None
    newest_at: datetime | None = None

    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0)) as client:
        while len(tweets) < count and pages < MAX_PAGES:
            params: dict[str, str] = {"query": query, "queryType": "Latest"}
            if cursor:
                params["cursor"] = cursor
            try:
                resp = await client.get(SEARCH_URL, params=params, headers={"x-api-key": api_key})
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                if pages == 0:
                    raise TwitterFetchError(str(exc)) from exc
                break

            batch = payload.get("tweets") or []
            fetched_total += len(batch)
            for item in batch:
                raw_text = str(item.get("text") or "")
                if is_collab_hashtag(raw_text):
                    excluded_collab += 1
                    continue
                reply_to = item.get("inReplyToUsername")
                if not tweet_matches_terms(
                    raw_text,
                    terms,
                    exclude_handle,
                    in_reply_to=str(reply_to) if reply_to else None,
                ):
                    filtered_out += 1
                    continue
                cleaned = clean_tweet_text(raw_text)
                key = cleaned.lower()
                if len(cleaned) >= MIN_TEXT_LENGTH and key not in seen:
                    seen.add(key)
                    created_at = parse_tweet_created_at(
                        item.get("createdAt") or item.get("created_at")
                    )
                    if created_at is not None:
                        if oldest_at is None or created_at < oldest_at:
                            oldest_at = created_at
                        if newest_at is None or created_at > newest_at:
                            newest_at = created_at
                    tweets.append(
                        TwitterTweet(
                            text=cleaned,
                            created_at=created_at,
                            url=tweet_url_from_item(item),
                            raw_text=_WS_RE.sub(" ", raw_text).strip(),
                            like_count=_coerce_engagement_count(item.get("likeCount")),
                            retweet_count=_coerce_engagement_count(item.get("retweetCount")),
                            reply_count=_coerce_engagement_count(item.get("replyCount")),
                            view_count=_coerce_engagement_count(item.get("viewCount")),
                        )
                    )
                    if len(tweets) >= count:
                        break
            pages += 1

            if on_page is not None:
                try:
                    await on_page(
                        TwitterFetchProgress(
                            pages_done=pages,
                            fetched_total=fetched_total,
                            tweets_found=len(tweets),
                            filtered_out=filtered_out,
                            excluded_collab=excluded_collab,
                            oldest_tweet_at=oldest_at,
                            newest_tweet_at=newest_at,
                        )
                    )
                except Exception:
                    _logger.warning("twitter fetch: on_page hook failed (non-fatal)", exc_info=True)

            if not payload.get("has_next_page") or not payload.get("next_cursor"):
                exhausted = True
                break
            cursor = str(payload["next_cursor"])
            await asyncio.sleep(PAGE_DELAY_SECONDS)

    return TwitterFetchResult(
        tweets=tweets,
        fetched_total=fetched_total,
        pages=pages,
        exhausted=exhausted,
        filtered_out=filtered_out,
        excluded_collab=excluded_collab,
        oldest_tweet_at=oldest_at,
        newest_tweet_at=newest_at,
    )
