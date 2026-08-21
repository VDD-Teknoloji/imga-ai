"""Operasyonel "facts" alanları için saf ayrıştırma yardımcıları.

I/O yok, DB oturumu yok — hem batch worker (``workers.batch_analyzer``
+ ``workers.file_parser``) hem de ``scripts/backfill_review_dates.py``
AYNI fonksiyonları kullanır, böylece bir satırın SLA/CSAT/efor/tazmin/
teslimat gerçekleşmesi ingestion anında da geriye dönük backfill'de de
BİREBİR AYNI kuralla parse edilir.

Ölçümle doğrulanmış kaynak veri (Navlungo SLA raporu) üzerinden:
  * SLA durumu: ``"Within SLA"`` / ``"SLA Violated"`` — başka değer yok.
  * Süre kolonları başlıkta "(saat olarak)" yazsa da HÜCRE DEĞERİ
    ``HH:MM:SS`` metnidir (saat kısmı 490+ olabilir) — asla datetime/
    time olarak parse edilmemeli, yalnız ':' ile bölünüp
    ``saat * 60 + dakika`` hesaplanır (saniye atılır).
  * CSAT: beş sabit Türkçe ifade + ``"N (Positive|Neutral|Negative)"``
    biçiminde baştaki rakam.

Yer tutucu normalizasyonu (``build_fact_row`` içinde uygulanır — hem
ingestion hem backfill bu TEK fonksiyonu çağırdığı için otomatik
ikisinde de geçerli): durum kolonu boş/tanınmayan (None) VE süre tam
0 dakikaysa, süre de None'a döner — "00:00:00" burada "veri yok"
yer tutucusudur, "0 dakikada çözüldü" değil.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

FACT_FIELDS: tuple[str, ...] = (
    "sla_resolution_status",
    "sla_first_response_status",
    "resolution_time",
    "first_response_time",
    "csat",
    "agent_interactions",
    "customer_interactions",
    "compensation_status",
    "freight_cost",
    "goods_cost",
    "refund_reason",
    "delivery_status",
    "delivery_detail",
)

_CSAT_EXACT_MAP: tuple[tuple[str, int], ...] = (
    # "hiç memnun değilim" MUTLAKA "memnun değilim"den ÖNCE kontrol
    # edilmeli — ikincisi birincinin alt-dizesi değil ama sıralama
    # yine de niyeti netleştiriyor (en spesifik önce).
    ("hiç memnun değilim", 1),
    ("memnun değilim", 2),
    ("orta", 3),
    ("memnunum, daha iyi olabilirdi", 4),
    ("çok memnunum", 5),
)

_CSAT_LEADING_DIGIT = re.compile(r"^[1-5]")


def parse_sla_status(value: str | None) -> str | None:
    """``"Within SLA"`` -> ``"within"``, ``"SLA Violated"`` -> ``"violated"``.
    Başka her değer (boş dahil) None."""
    if value is None:
        return None
    text = value.strip().casefold()
    if text == "within sla":
        return "within"
    if text == "sla violated":
        return "violated"
    return None


def parse_duration_minutes(value: str | None) -> int | None:
    """``"HH:MM:SS"`` -> ``saat * 60 + dakika`` (saniye atılır). Saat
    kısmı 490+ olabilir — ASLA datetime/time parse edilmez, yalnız
    ':' ile üç parçaya bölünür. Üç parça değilse ya da parçalar
    tam sayı değilse None."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        int(parts[2])  # saniye doğrulanır ama hesaba katılmaz
    except ValueError:
        return None
    if hours < 0 or minutes < 0:
        return None
    return hours * 60 + minutes


def parse_int(value: str | None) -> int | None:
    """Tam sayı metni -> int. Boş/parse edilemeyen None. ``"5.0"`` gibi
    tam sayıya denk gelen ondalık metinler de kabul edilir (etkileşim
    sayacı kolonları bazen ondalık biçimli export edilir)."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        as_float = float(text.replace(",", "."))
    except ValueError:
        return None
    if as_float.is_integer():
        return int(as_float)
    return None


def parse_decimal(value: str | None) -> Decimal | None:
    """``"863.62"`` (nokta) ya da ``"863,62"`` (virgül, noktaya
    çevrilir) -> ``Decimal``. Boş/parse edilemeyen None."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def parse_text(value: str | None) -> str | None:
    """Serbest metin alanları (tazmin durumu, iade sebebi, teslimat
    durumu/detayı) için ortak trim kuralı: boş -> None."""
    if value is None:
        return None
    text = value.strip()
    return text or None


def parse_csat(value: str | None) -> tuple[int | None, str | None]:
    """Anket sonucu hücresini ``(csat_score, csat_raw)``'a çevirir.

    ``csat_raw`` her zaman trim'li ham metindir — eşleşmese bile
    korunur (yalnız hücre gerçekten boşsa ikisi de None). Beş sabit
    Türkçe ifade (casefold karşılaştırma) ve ``"N (Positive)"`` gibi
    baştaki 1-5 rakamı tanınır; başka hiçbir değer skor üretmez."""
    if value is None:
        return None, None
    raw = value.strip()
    if not raw:
        return None, None
    folded = raw.casefold()
    for phrase, score in _CSAT_EXACT_MAP:
        if folded == phrase:
            return score, raw
    match = _CSAT_LEADING_DIGIT.match(raw)
    if match:
        return int(match.group()), raw
    return None, raw


def build_fact_row(raw_values: dict[str, str]) -> dict[str, Any] | None:
    """``{fact_field: ham_deger}`` -> review_facts kolon sözlüğü.

    ``raw_values`` yalnız BU satırda gerçekten dolu hücresi olan
    ``fact_field``'leri taşır (worker: ``ParsedRow.facts``; backfill:
    o komuttaki ``--fact`` hedeflerinden derlenen tek-satırlık
    sözlük) — eksik anahtar "bu alan bu satırda/komutta yok" demektir,
    boş string DEĞİL.

    Dönen sözlük HER ZAMAN aynı 14 kolon anahtarını taşır (dolu/boş
    karışık None'larla) — çağıranların (worker'ın toplu upsert'i,
    backfill'in executemany'si) tek bir ``insert().values([...])``
    çağrısında birleştirebilmesi için. Hiçbir alan dolu değilse (13
    fact_field'in TAMAMI eksik/boş/parse edilemez) ``None`` döner —
    review_facts'e boş bir satır yazılmaz.

    Yer tutucu normalizasyonu burada uygulanır: durum None VE süre tam
    0 dakikaysa süre de None'a düşer (modül docstring'i).
    """
    sla_resolution_status = parse_sla_status(
        raw_values.get("sla_resolution_status")
    )
    resolution_time_minutes = parse_duration_minutes(
        raw_values.get("resolution_time")
    )
    if sla_resolution_status is None and resolution_time_minutes == 0:
        resolution_time_minutes = None

    sla_first_response_status = parse_sla_status(
        raw_values.get("sla_first_response_status")
    )
    first_response_time_minutes = parse_duration_minutes(
        raw_values.get("first_response_time")
    )
    if sla_first_response_status is None and first_response_time_minutes == 0:
        first_response_time_minutes = None

    csat_score, csat_raw = parse_csat(raw_values.get("csat"))

    row: dict[str, Any] = {
        "sla_resolution_status": sla_resolution_status,
        "sla_first_response_status": sla_first_response_status,
        "resolution_time_minutes": resolution_time_minutes,
        "first_response_time_minutes": first_response_time_minutes,
        "csat_score": csat_score,
        "csat_raw": csat_raw,
        "agent_interactions": parse_int(raw_values.get("agent_interactions")),
        "customer_interactions": parse_int(
            raw_values.get("customer_interactions")
        ),
        "compensation_status": parse_text(
            raw_values.get("compensation_status")
        ),
        "freight_cost": parse_decimal(raw_values.get("freight_cost")),
        "goods_cost": parse_decimal(raw_values.get("goods_cost")),
        "refund_reason": parse_text(raw_values.get("refund_reason")),
        "delivery_status": parse_text(raw_values.get("delivery_status")),
        "delivery_detail": parse_text(raw_values.get("delivery_detail")),
    }
    if all(v is None for v in row.values()):
        return None
    return row


__all__ = [
    "FACT_FIELDS",
    "build_fact_row",
    "parse_csat",
    "parse_decimal",
    "parse_duration_minutes",
    "parse_int",
    "parse_sla_status",
    "parse_text",
]
