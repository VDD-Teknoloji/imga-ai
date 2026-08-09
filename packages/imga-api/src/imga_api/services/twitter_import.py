"""twitterapi.io üzerinden tweet çekimi — "Twitter'dan Çek" entegrasyonu.

imga.ai pazarlama sitesindeki trial akışının (site repo'su
``src/lib/twitter.ts``) sunucu tarafı karşılığı: advanced_search
sayfalı çekim + temizle/dedupe. Anahtar kelime çıkarımı (Gemini) bilerek
yok — kullanıcı arama terimini kendisi verir; sorgu deterministik kalır.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

SEARCH_URL = "https://api.twitterapi.io/twitter/tweet/advanced_search"
# twitterapi.io sayfa başına ~20 tweet döner; 1000 hedefi için 80 sayfa
# üst sınır yeterli (pratikte sorgu çok daha erken tükenir).
MAX_PAGES = 80
PAGE_DELAY_SECONDS = 0.3
MIN_TEXT_LENGTH = 5

_URL_RE = re.compile(r"https?://\S+")
_LEADING_MENTIONS_RE = re.compile(r"^(?:@\w+\s+)+")
_WS_RE = re.compile(r"\s+")

# twitterapi.io tweet'in atılma anını Twitter'ın klasik biçiminde
# döner ("Tue Dec 10 07:00:30 +0000 2024"). ISO da görülebiliyor, o
# yüzden iki deneme.
_TWITTER_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"


class TwitterFetchError(Exception):
    """twitterapi.io'ya ilk sayfada bile ulaşılamadı (ağ / auth / kota)."""


@dataclass(frozen=True, slots=True)
class TwitterTweet:
    """Tek tweet: temizlenmiş metin + atılma anı.

    ``created_at`` None ise tarih çözülemedi — batch pipeline yorumun
    kendi tarihi olarak ingest anına düşer (yorum kaybolmaz)."""

    text: str
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class TwitterFetchResult:
    tweets: list[TwitterTweet]
    fetched_total: int
    pages: int
    # True → sayfalama bitti; istenen sayıya ulaşılamadıysa X'te bu
    # sorgu için daha fazla Türkçe sonuç yok demektir.
    exhausted: bool


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


def build_search_query(term: str, exclude_handle: str | None) -> str:
    """Site ile aynı sorgu dili: terim tırnaklı, Türkçe, RT'siz; resmi
    hesap verilmişse onun kendi paylaşımları hariç (müşteri sesi değil)."""
    handle = (exclude_handle or "").lstrip("@").strip()
    parts = [f'"{term}"']
    if handle:
        parts.append(f"-from:{handle}")
    parts.append("lang:tr -filter:retweets")
    return " ".join(parts)


def clean_tweet_text(raw: str) -> str:
    """URL'leri ve baştaki @mention zincirini at, boşlukları normalize et."""
    text = _URL_RE.sub("", raw)
    text = _LEADING_MENTIONS_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


async def fetch_tweets(
    *,
    api_key: str,
    term: str,
    count: int,
    exclude_handle: str | None = None,
) -> TwitterFetchResult:
    """En yeni tweetlerden ``count`` temiz metin + tarih topla.

    İlk sayfa hatası ``TwitterFetchError`` olarak yükselir; sonraki
    sayfalardaki hatalar eldeki kısmi sonuçla sessizce döner (yarım
    veri, sıfır veriden iyidir — batch pipeline gerisini halleder).
    """
    query = build_search_query(term, exclude_handle)
    tweets: list[TwitterTweet] = []
    seen: set[str] = set()
    fetched_total = 0
    pages = 0
    cursor = ""
    exhausted = False

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
                cleaned = clean_tweet_text(str(item.get("text") or ""))
                key = cleaned.lower()
                if len(cleaned) >= MIN_TEXT_LENGTH and key not in seen:
                    seen.add(key)
                    tweets.append(
                        TwitterTweet(
                            text=cleaned,
                            created_at=parse_tweet_created_at(
                                item.get("createdAt") or item.get("created_at")
                            ),
                        )
                    )
                    if len(tweets) >= count:
                        break
            pages += 1

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
    )
