"""Unit coverage for imga_api.services.fact_parsing.

No DB, no async — these are pure functions (ingestion worker AND
scripts/backfill_review_dates.py share them, migration 0046). Values
below are drawn from the measured source data (Navlungo SLA raporu):
'Within SLA' / 'SLA Violated' status strings, HH:MM:SS duration cells
(despite the "(saat olarak)" header wording), and the five fixed
Turkish CSAT phrases + 'N (Positive/Neutral/Negative)' leading-digit
form.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from imga_api.services.fact_parsing import (
    FACT_FIELDS,
    build_fact_row,
    parse_csat,
    parse_decimal,
    parse_duration_minutes,
    parse_int,
    parse_sla_status,
    parse_text,
)

# --- FACT_FIELDS -------------------------------------------------------


def test_fact_fields_has_13_entries_no_duplicates() -> None:
    assert len(FACT_FIELDS) == 13
    assert len(set(FACT_FIELDS)) == 13


# --- parse_sla_status ----------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Within SLA", "within"),
        ("within sla", "within"),
        ("  WITHIN SLA  ", "within"),
        ("SLA Violated", "violated"),
        ("sla violated", "violated"),
        ("", None),
        (None, None),
        ("Beklemede", None),
        ("Within", None),
    ],
)
def test_parse_sla_status(raw: str | None, expected: str | None) -> None:
    assert parse_sla_status(raw) == expected


# --- parse_duration_minutes ----------------------------------------------


def test_parse_duration_minutes_ignores_seconds() -> None:
    assert parse_duration_minutes("00:14:19") == 14


def test_parse_duration_minutes_large_hour_part() -> None:
    """490:00:00 -> saat kısmı 490+ olabilir; ASLA datetime parse
    edilmez, yalnız h*60+m hesaplanır."""
    assert parse_duration_minutes("490:00:00") == 490 * 60


def test_parse_duration_minutes_measured_value() -> None:
    """Kaynak veriden ölçülen gerçek bir hücre: 113:11:57 -> 113*60+11."""
    assert parse_duration_minutes("113:11:57") == 113 * 60 + 11


def test_parse_duration_minutes_zero() -> None:
    assert parse_duration_minutes("00:00:00") == 0


@pytest.mark.parametrize(
    "raw",
    [None, "", "00:00", "not-a-duration", "1:2:3:4", "aa:bb:cc", "-1:00:00", "01:-5:00"],
)
def test_parse_duration_minutes_rejects_bad_input(raw: str | None) -> None:
    assert parse_duration_minutes(raw) is None


# --- parse_int / parse_decimal -------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [("5", 5), ("0", 0), ("  12 ", 12), ("5.0", 5), (None, None), ("", None), ("abc", None), ("5.5", None)],
)
def test_parse_int(raw: str | None, expected: int | None) -> None:
    assert parse_int(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("863.62", "863.62"),
        ("863,62", "863.62"),
        ("1205.0", "1205.0"),
        (None, None),
        ("", None),
        ("not-a-number", None),
    ],
)
def test_parse_decimal(raw: str | None, expected: str | None) -> None:
    result = parse_decimal(raw)
    if expected is None:
        assert result is None
    else:
        assert result == Decimal(expected)


# --- parse_text ------------------------------------------------------


def test_parse_text_trims_and_nulls_blank() -> None:
    assert parse_text("  Onaylandı  ") == "Onaylandı"
    assert parse_text("   ") is None
    assert parse_text("") is None
    assert parse_text(None) is None


# --- parse_csat ------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected_score",
    [
        ("Çok memnunum", 5),
        ("çok memnunum", 5),
        ("Memnunum, daha iyi olabilirdi", 4),
        ("Orta", 3),
        ("Memnun değilim", 2),
        ("Hiç memnun değilim", 1),
        ("hiç memnun değilim", 1),
        ("5 (Positive)", 5),
        ("1 (Negative)", 1),
        ("3 (Neutral)", 3),
    ],
)
def test_parse_csat_recognized_values(raw: str, expected_score: int) -> None:
    score, csat_raw = parse_csat(raw)
    assert score == expected_score
    assert csat_raw == raw.strip()


def test_parse_csat_hic_memnun_degilim_not_confused_with_memnun_degilim() -> None:
    """'Hiç memnun değilim' -> 1, ASLA 'memnun değilim' (2) alt-dizesiyle
    karışmamalı — sıralama/eşleme kuralı burada test edilir."""
    assert parse_csat("Hiç memnun değilim") == (1, "Hiç memnun değilim")


def test_parse_csat_unrecognized_keeps_raw_returns_none_score() -> None:
    score, raw = parse_csat("beklenmedik bir metin")
    assert score is None
    assert raw == "beklenmedik bir metin"


def test_parse_csat_empty_returns_none_none() -> None:
    assert parse_csat("") == (None, None)
    assert parse_csat("   ") == (None, None)
    assert parse_csat(None) == (None, None)


# --- build_fact_row --------------------------------------------------


def test_build_fact_row_returns_none_when_all_empty() -> None:
    assert build_fact_row({}) is None
    assert build_fact_row({"sla_resolution_status": ""}) is None


def test_build_fact_row_placeholder_normalization_resolution_pair() -> None:
    """7.153/7.400 durum-boş satır vakası: statü boş/tanınmayan VE süre
    tam 0 dakikaysa süre de None'a düşer. csat de verilerek satırın
    (normalizasyon sonrası tamamen boş kalıp None dönmek yerine)
    gerçekten yazıldığı doğrulanıyor."""
    row = build_fact_row(
        {
            "sla_resolution_status": "",
            "resolution_time": "00:00:00",
            "csat": "Orta",
        }
    )
    assert row is not None
    assert row["sla_resolution_status"] is None
    assert row["resolution_time_minutes"] is None


def test_build_fact_row_placeholder_normalization_first_response_pair() -> None:
    row = build_fact_row({"first_response_time": "00:00:00", "csat": "Orta"})
    assert row is not None
    assert row["sla_first_response_status"] is None
    assert row["first_response_time_minutes"] is None


def test_build_fact_row_placeholder_only_row_returns_none() -> None:
    """Satırdaki TEK veri yer tutucu çiftiyse (statü boş + süre 0),
    normalizasyon sonrası tüm alanlar None'a düşer ve build_fact_row
    'hiç dolu alan yok' kuralına göre None döner — review_facts'e
    anlamsız bir 0-dakika satırı yazılmaz."""
    assert (
        build_fact_row(
            {"sla_resolution_status": "", "resolution_time": "00:00:00"}
        )
        is None
    )


def test_build_fact_row_zero_duration_kept_when_status_present() -> None:
    """Statü DOLU ve süre 0 ise (gerçekten 0 dakikada çözüldü), 0
    korunur — normalizasyon yalnız statü None İKEN tetiklenir."""
    row = build_fact_row(
        {"sla_resolution_status": "Within SLA", "resolution_time": "00:00:00"}
    )
    assert row is not None
    assert row["sla_resolution_status"] == "within"
    assert row["resolution_time_minutes"] == 0


def test_build_fact_row_nonzero_duration_kept_when_status_absent() -> None:
    """Yer tutucu kuralı yalnız TAM 0 dakika için geçerli — 14 dakika
    gibi gerçek bir süre statü boş olsa bile silinmez."""
    row = build_fact_row({"resolution_time": "00:14:19"})
    assert row is not None
    assert row["sla_resolution_status"] is None
    assert row["resolution_time_minutes"] == 14


def test_build_fact_row_csat_writes_both_columns() -> None:
    row = build_fact_row({"csat": "Çok memnunum"})
    assert row is not None
    assert row["csat_score"] == 5
    assert row["csat_raw"] == "Çok memnunum"


def test_build_fact_row_full_row_measured_values() -> None:
    row = build_fact_row(
        {
            "sla_resolution_status": "SLA Violated",
            "resolution_time": "113:11:57",
            "sla_first_response_status": "Within SLA",
            "first_response_time": "00:14:19",
            "csat": "3 (Neutral)",
            "agent_interactions": "5",
            "customer_interactions": "1",
            "compensation_status": "Onaylandı",
            "freight_cost": "1117.72",
            "goods_cost": "1185.0",
            "refund_reason": "Hasar",
            "delivery_status": "Teslim Edildi",
            "delivery_detail": "Adres Sorunu",
        }
    )
    assert row is not None
    freight_cost = row.pop("freight_cost")
    goods_cost = row.pop("goods_cost")
    assert freight_cost == Decimal("1117.72")
    assert goods_cost == Decimal("1185.0")
    assert row == {
        "sla_resolution_status": "violated",
        "sla_first_response_status": "within",
        "resolution_time_minutes": 113 * 60 + 11,
        "first_response_time_minutes": 14,
        "csat_score": 3,
        "csat_raw": "3 (Neutral)",
        "agent_interactions": 5,
        "customer_interactions": 1,
        "compensation_status": "Onaylandı",
        "refund_reason": "Hasar",
        "delivery_status": "Teslim Edildi",
        "delivery_detail": "Adres Sorunu",
    }


def test_build_fact_row_missing_key_means_no_data_not_empty_string() -> None:
    """Eksik anahtar (bu koşuda hiç gelmemiş alan) None üretir — boş
    string ile aynı davranır ama build_fact_row'a hiç girmeyen alanlar
    normalizasyon kuralını TETİKLEMEZ (yalnız statü+süre ÇİFTİ aynı
    sözlükte birlikte değerlendirilir)."""
    row = build_fact_row({"csat": "Orta"})
    assert row is not None
    assert row["sla_resolution_status"] is None
    assert row["resolution_time_minutes"] is None
    assert row["csat_score"] == 3
