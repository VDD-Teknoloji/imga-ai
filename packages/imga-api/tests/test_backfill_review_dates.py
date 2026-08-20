"""Unit tests for scripts/backfill_review_dates.py's pure logic.

``scripts/`` has no ``__init__.py`` — it's not an importable package —
so the script is loaded via ``importlib.util.spec_from_file_location``
rather than a normal ``import``. Only the SAF (pure, I/O-less) functions
(``match_dates_by_hash_order`` / ``match_values_by_hash_order``,
``safety_check``, ``should_write_target_value`` /
``split_writable_assignments``, ``map_quality_label``,
``has_automation_notification_tag`` / ``map_tags_to_quality_label``,
``merge_quality_flag_assignments``) and the file-reading helpers
(``extract_file_dates_by_hash`` / ``extract_file_column_values_by_hash``,
exercised against real temp files — CSV and XLSX) are covered here — no
DB, mirrors test_file_parser.py's "runs without a DB" scope. The DB
round-trip (``fetch_db_rows_by_hash``, ``fetch_current_column_values``,
``_apply_column_update``, ``run()``) needs live Postgres and is out of
scope for this file; it's covered by manual --dry-run verification per
the script's own docstring.
"""

from __future__ import annotations

import csv
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest


def _find_script() -> Path | None:
    """Repo düzeninde (tests -> imga-api -> packages -> kök) ve test
    konteynerinde (/app/tests + /app/scripts ro-mount) çalışır; ikisi de
    yoksa None — parents[i] konteynerin sığ yolunda IndexError atardı."""
    here = Path(__file__).resolve()
    candidates = [parent / "scripts" / "backfill_review_dates.py" for parent in here.parents]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


_SCRIPT_PATH = _find_script()
if _SCRIPT_PATH is None:
    pytest.skip(
        "scripts/backfill_review_dates.py bulunamadi (mount edilmemis)",
        allow_module_level=True,
    )


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backfill_review_dates", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backfill = _load_script_module()


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)


def _dt(day: int, month: int = 5, year: int = 2026) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


# --- match_dates_by_hash_order -------------------------------------------


def test_match_unique_hash_is_exact() -> None:
    """Tekil hash (dosyada 1 tarih, DB'de 1 satır): eşleme birebir kesin."""
    review_id = uuid4()
    assignments = backfill.match_dates_by_hash_order(
        file_dates_by_hash={"h1": [_dt(5)]},
        db_rows_by_hash={"h1": [(review_id, _dt(1, month=1))]},
    )
    assert assignments == {review_id: _dt(5)}


def test_match_repeated_hash_aggregate_distribution_exact() -> None:
    """Tekrarlı hash (şablon metin 3 kez): dosyadaki 3 tarihin TÜMÜ
    kullanılır — agrega dağılım birebir doğru. DB satırları analyzed_at
    sırasına göre atanır (en eski analyzed_at -> dosyanın ilk tarihi)."""
    r_old, r_mid, r_new = uuid4(), uuid4(), uuid4()
    db_rows = {
        "h1": [
            (r_new, datetime(2026, 1, 3, tzinfo=UTC)),
            (r_old, datetime(2026, 1, 1, tzinfo=UTC)),
            (r_mid, datetime(2026, 1, 2, tzinfo=UTC)),
        ]
    }
    file_dates = {"h1": [_dt(10), _dt(11), _dt(12)]}
    assignments = backfill.match_dates_by_hash_order(file_dates, db_rows)
    # analyzed_at sırası: r_old(1.) < r_mid(2.) < r_new(3.) -> dosya sırası
    # (10, 11, 12) da bu sırayla eşlenir.
    assert assignments == {r_old: _dt(10), r_mid: _dt(11), r_new: _dt(12)}
    # Agrega: kullanılan tarih kümesi dosyadakiyle birebir aynı.
    assert sorted(assignments.values()) == sorted(file_dates["h1"])


def test_match_hash_only_in_file_is_skipped() -> None:
    """DB'de karşılığı olmayan bir dosya hash'i sessizce atlanır — hiçbir
    atama üretmez (çağıran taraf bunu ayrı, safety_check ile sayar)."""
    assignments = backfill.match_dates_by_hash_order(
        file_dates_by_hash={"only-in-file": [_dt(5)]},
        db_rows_by_hash={},
    )
    assert assignments == {}


def test_match_hash_only_in_db_is_left_untouched() -> None:
    """Dosyada karşılığı olmayan bir DB hash'i güncellenmez — çıktı
    dict'inde hiç görünmez (mevcut review_date korunur)."""
    review_id = uuid4()
    assignments = backfill.match_dates_by_hash_order(
        file_dates_by_hash={},
        db_rows_by_hash={"only-in-db": [(review_id, _dt(1))]},
    )
    assert review_id not in assignments
    assert assignments == {}


def test_match_more_file_dates_than_db_rows_uses_only_min() -> None:
    """Dosyada 3 tarih ama DB'de yalnız 2 satır (ör. bir satır
    failed_rows'a düştü) — yalnız ilk 2 tarih kullanılır, 3.'sü hiçbir
    yere yazılmaz."""
    r1, r2 = uuid4(), uuid4()
    db_rows = {
        "h1": [
            (r1, datetime(2026, 1, 1, tzinfo=UTC)),
            (r2, datetime(2026, 1, 2, tzinfo=UTC)),
        ]
    }
    file_dates = {"h1": [_dt(10), _dt(11), _dt(12)]}
    assignments = backfill.match_dates_by_hash_order(file_dates, db_rows)
    assert assignments == {r1: _dt(10), r2: _dt(11)}
    assert len(assignments) == 2


def test_match_more_db_rows_than_file_dates_leaves_excess_unassigned() -> None:
    """DB'de 3 satır ama dosyada yalnız 1 tarih — yalnız 1 satır
    güncellenir, kalan 2 mevcut review_date'ini korur (çıktıda yok)."""
    r1, r2, r3 = uuid4(), uuid4(), uuid4()
    db_rows = {
        "h1": [
            (r1, datetime(2026, 1, 1, tzinfo=UTC)),
            (r2, datetime(2026, 1, 2, tzinfo=UTC)),
            (r3, datetime(2026, 1, 3, tzinfo=UTC)),
        ]
    }
    file_dates = {"h1": [_dt(10)]}
    assignments = backfill.match_dates_by_hash_order(file_dates, db_rows)
    assert assignments == {r1: _dt(10)}
    assert r2 not in assignments
    assert r3 not in assignments


def test_match_ties_in_analyzed_at_break_by_id() -> None:
    """analyzed_at eşitse sıralama id'ye (str karşılaştırma) düşer —
    sonuç deterministik olmalı, hangi id küçükse o önce."""
    same_moment = datetime(2026, 1, 1, tzinfo=UTC)
    ids = sorted([uuid4(), uuid4()], key=str)
    smaller_id, larger_id = ids[0], ids[1]
    db_rows = {
        "h1": [
            (larger_id, same_moment),
            (smaller_id, same_moment),
        ]
    }
    file_dates = {"h1": [_dt(10), _dt(20)]}
    assignments = backfill.match_dates_by_hash_order(file_dates, db_rows)
    assert assignments == {smaller_id: _dt(10), larger_id: _dt(20)}


def test_match_multiple_hashes_independent() -> None:
    r_a, r_b = uuid4(), uuid4()
    file_dates = {"a": [_dt(1)], "b": [_dt(2)]}
    db_rows = {
        "a": [(r_a, datetime(2026, 1, 1, tzinfo=UTC))],
        "b": [(r_b, datetime(2026, 1, 1, tzinfo=UTC))],
    }
    assignments = backfill.match_dates_by_hash_order(file_dates, db_rows)
    assert assignments == {r_a: _dt(1), r_b: _dt(2)}


def test_match_empty_inputs_yield_empty_output() -> None:
    assert backfill.match_dates_by_hash_order({}, {}) == {}


# --- safety_check -----------------------------------------------------


def test_safety_check_perfect_overlap_zero_ratio() -> None:
    review_id = uuid4()
    unmatched_file, unmatched_db, ratio = backfill.safety_check(
        file_row_counts_by_hash={"h1": 3},
        db_rows_by_hash={"h1": [(review_id, _dt(1)), (review_id, _dt(2)), (review_id, _dt(3))]},
    )
    assert (unmatched_file, unmatched_db) == (0, 0)
    assert ratio == 0.0


def test_safety_check_measures_unmatched_both_directions() -> None:
    r1, r2 = uuid4(), uuid4()
    unmatched_file, unmatched_db, ratio = backfill.safety_check(
        file_row_counts_by_hash={"shared": 8, "file-only": 2},
        db_rows_by_hash={
            "shared": [(r1, _dt(1))] * 8,
            "db-only": [(r2, _dt(1))],
        },
    )
    # total_file_rows = 10 (8 + 2); unmatched = 2 (file-only) + 1 (db-only) = 3
    assert unmatched_file == 2
    assert unmatched_db == 1
    assert ratio == 3 / 10


def test_safety_check_empty_file_side_is_zero_ratio_not_divide_error() -> None:
    _unmatched_file, unmatched_db, ratio = backfill.safety_check(
        file_row_counts_by_hash={},
        db_rows_by_hash={"h1": [(uuid4(), _dt(1))]},
    )
    assert ratio == 0.0
    assert unmatched_db == 1


def test_safety_check_above_threshold_would_abort() -> None:
    """Eşik %2 — %3 eşleşmeyen bir dosya bu eşiğin üzerinde kalmalı
    (script'in ana akışı bu durumda ABORT eder)."""
    _unmatched_file, _unmatched_db, ratio = backfill.safety_check(
        file_row_counts_by_hash={"shared": 97, "file-only": 3},
        db_rows_by_hash={"shared": [(uuid4(), _dt(1))] * 97},
    )
    assert ratio == 3 / 100
    assert ratio > backfill._MISMATCH_ABORT_THRESHOLD


# --- extract_file_dates_by_hash (gerçek geçici dosya, DB yok) ----------


def test_extract_file_dates_by_hash_groups_and_orders(tmp_path: Path) -> None:
    path = tmp_path / "backfill-source.csv"
    _write_csv(
        path,
        [
            ["yorum", "tarih"],
            ["tekrar eden yorum", "01.05.2026"],
            ["tekil yorum", "02.05.2026"],
            ["tekrar eden yorum", "03.05.2026"],
            ["", "04.05.2026"],  # boş metin — tamamen dışlanır
            ["tarihsiz yorum", "gecersiz-tarih"],  # sayaçta var, tarih listesinde yok
        ],
    )
    dates_by_hash, counts_by_hash = backfill.extract_file_dates_by_hash(
        path, text_column="yorum", date_column=None
    )
    from imga_core.text_utils import review_text_hash

    repeated_hash = review_text_hash("tekrar eden yorum")
    unique_hash = review_text_hash("tekil yorum")
    dateless_hash = review_text_hash("tarihsiz yorum")

    assert dates_by_hash[repeated_hash] == [_dt(1), _dt(3)]
    assert dates_by_hash[unique_hash] == [_dt(2)]
    # Tarihi çözülmeyen satır dates_by_hash'te YOK ama counts_by_hash'te var.
    assert dateless_hash not in dates_by_hash
    assert counts_by_hash[dateless_hash] == 1
    assert counts_by_hash[repeated_hash] == 2
    assert counts_by_hash[unique_hash] == 1
    # Boş metinli satır ikisinde de yok.
    assert sum(counts_by_hash.values()) == 4  # 5 veri satırı - 1 boş


def test_extract_file_dates_by_hash_respects_explicit_date_column(
    tmp_path: Path,
) -> None:
    path = tmp_path / "explicit.csv"
    _write_csv(
        path,
        [["yorum", "tarih", "Kayıt Günü"], ["bir yorum", "01.01.2026", "15.03.2026"]],
    )
    dates_by_hash, _counts = backfill.extract_file_dates_by_hash(
        path, text_column="yorum", date_column="Kayıt Günü"
    )
    from imga_core.text_utils import review_text_hash

    h = review_text_hash("bir yorum")
    assert dates_by_hash[h] == [datetime(2026, 3, 15, tzinfo=UTC)]


# --- match_values_by_hash_order (genelleştirilmiş eşleme) --------------


def test_match_values_by_hash_order_assigns_none_positionally() -> None:
    """Genel eşleme None değerleri de POZİSYONEL olarak atar — map
    hedefleri için boş hücre gerçek bir NULL-yazma isteğidir, tarihin
    aksine listeden hiç atılmaz (bkz. extract_file_column_values_by_
    hash'in docstring'i)."""
    r1, r2 = uuid4(), uuid4()
    db_rows = {
        "h1": [
            (r1, datetime(2026, 1, 1, tzinfo=UTC)),
            (r2, datetime(2026, 1, 2, tzinfo=UTC)),
        ]
    }
    file_values: dict[str, list[str | None]] = {"h1": ["Website", None]}
    assignments = backfill.match_values_by_hash_order(file_values, db_rows)
    assert assignments == {r1: "Website", r2: None}


def test_match_values_by_hash_order_matches_dates_helper_behaviour() -> None:
    """match_dates_by_hash_order artık ince bir sarmalayıcı — aynı
    girdide aynı sonucu üretmeli."""
    review_id = uuid4()
    file_dates = {"h1": [_dt(5)]}
    db_rows = {"h1": [(review_id, _dt(1, month=1))]}
    assert backfill.match_values_by_hash_order(
        file_dates, db_rows
    ) == backfill.match_dates_by_hash_order(file_dates, db_rows)


# --- map_quality_label (--quality-label-column eşleme tablosu) ---------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mükerrer", "duplicate"),
        ("Mükerrer", "duplicate"),
        ("  MÜKERRER  ", "duplicate"),
        ("bilgi", "informational"),
        ("Bilgi", "informational"),
        ("  BİLGİ  ", "informational"),
        ("şikayet", None),
        ("talep", None),
        ("teşekkür", None),
        ("yardım", None),
        ("", None),
        ("   ", None),
        (None, None),
        ("bilinmeyen-bir-değer", None),
    ],
)
def test_map_quality_label(raw: str | None, expected: str | None) -> None:
    assert backfill.map_quality_label(raw) == expected


# --- has_automation_notification_tag / map_tags_to_quality_label -------


def test_has_automation_notification_tag_exact_match() -> None:
    assert backfill.has_automation_notification_tag("otomasyon bildirim") is True


def test_has_automation_notification_tag_among_multiple_tags() -> None:
    assert (
        backfill.has_automation_notification_tag("şikayet, otomasyon bildirim, öncelik-yüksek")
        is True
    )


def test_has_automation_notification_tag_case_and_whitespace_folded() -> None:
    assert backfill.has_automation_notification_tag(" Otomasyon Bildirim ,başka") is True


def test_has_automation_notification_tag_substring_is_not_a_match() -> None:
    """Alt-dize eşleşmesi SAYILMAZ — 'otomasyon bildirimi' ya da 'ön
    otomasyon bildirim' tam etikete eşit değildir."""
    assert backfill.has_automation_notification_tag("otomasyon bildirimi yapıldı") is False
    assert backfill.has_automation_notification_tag("ön otomasyon bildirim") is False


def test_has_automation_notification_tag_absent() -> None:
    assert backfill.has_automation_notification_tag("şikayet, talep") is False


def test_has_automation_notification_tag_none_or_empty() -> None:
    assert backfill.has_automation_notification_tag(None) is False
    assert backfill.has_automation_notification_tag("") is False


def test_map_tags_to_quality_label() -> None:
    assert backfill.map_tags_to_quality_label("otomasyon bildirim") == "informational"
    assert backfill.map_tags_to_quality_label("şikayet") is None
    assert backfill.map_tags_to_quality_label(None) is None


# --- merge_quality_flag_assignments -------------------------------------


def test_merge_quality_flag_assignments_label_wins_on_conflict() -> None:
    r_conflict, r_label_only, r_tags_only = uuid4(), uuid4(), uuid4()
    label = {r_conflict: "duplicate", r_label_only: "informational"}
    tags = {r_conflict: "informational", r_tags_only: "informational"}
    merged = backfill.merge_quality_flag_assignments(label, tags)
    assert merged == {
        r_conflict: "duplicate",  # quality-label-column kazanir
        r_label_only: "informational",
        r_tags_only: "informational",
    }


def test_merge_quality_flag_assignments_single_source_passthrough() -> None:
    review_id = uuid4()
    assert backfill.merge_quality_flag_assignments({review_id: "duplicate"}, {}) == {
        review_id: "duplicate"
    }
    assert backfill.merge_quality_flag_assignments({}, {review_id: "informational"}) == {
        review_id: "informational"
    }


# --- should_write_target_value / split_writable_assignments ------------


@pytest.mark.parametrize(
    ("current_value", "overwrite", "expected"),
    [
        (None, False, True),
        (None, True, True),
        ("mevcut", False, False),
        ("mevcut", True, True),
        ("", False, False),  # bos string NULL DEGIL -- mevcut sayilir
    ],
)
def test_should_write_target_value(
    current_value: str | None, overwrite: bool, expected: bool
) -> None:
    assert backfill.should_write_target_value(current_value, overwrite=overwrite) is expected


def test_split_writable_assignments_no_overwrite_skips_existing() -> None:
    r_null, r_has_value = uuid4(), uuid4()
    assignments = {r_null: "Website", r_has_value: "Mobil"}
    current_values = {r_null: None, r_has_value: "Zaten Var"}
    to_write, skipped = backfill.split_writable_assignments(
        assignments, current_values, overwrite=False
    )
    assert to_write == {r_null: "Website"}
    assert skipped == 1


def test_split_writable_assignments_overwrite_writes_all() -> None:
    r1, r2 = uuid4(), uuid4()
    assignments = {r1: "Website", r2: "Mobil"}
    current_values = {r1: None, r2: "Zaten Var"}
    to_write, skipped = backfill.split_writable_assignments(
        assignments, current_values, overwrite=True
    )
    assert to_write == {r1: "Website", r2: "Mobil"}
    assert skipped == 0


def test_split_writable_assignments_missing_current_value_treated_as_null() -> None:
    """current_values'ta karşılığı olmayan id — fetch_current_column_
    values'ın gerçek akışta üretmeyeceği ama savunma amaçlı ele alınan
    bir durum — NULL kabul edilir (yazılabilir)."""
    review_id = uuid4()
    to_write, skipped = backfill.split_writable_assignments(
        {review_id: "Website"}, {}, overwrite=False
    )
    assert to_write == {review_id: "Website"}
    assert skipped == 0


# --- extract_file_column_values_by_hash (gerçek geçici dosya, DB yok) --


def test_extract_file_column_values_by_hash_groups_orders_and_keeps_none(
    tmp_path: Path,
) -> None:
    """extract_file_dates_by_hash'in hash+sıra mantığıyla AYNI, ama boş
    değerler ATILMAZ (tarihin aksine) — None pozisyonda kalır."""
    path = tmp_path / "backfill-values.csv"
    _write_csv(
        path,
        [
            ["yorum", "kaynak"],
            ["tekrar eden yorum", "Website"],
            ["tekil yorum", ""],
            ["tekrar eden yorum", "Mobil"],
            ["", "BosMetinSatiri"],  # bos metin -- tamamen dislanir
        ],
    )
    values_by_target = backfill.extract_file_column_values_by_hash(
        path, text_column="yorum", value_columns={"source": "kaynak"}
    )
    from imga_core.text_utils import review_text_hash

    repeated_hash = review_text_hash("tekrar eden yorum")
    unique_hash = review_text_hash("tekil yorum")

    assert values_by_target["source"][repeated_hash] == ["Website", "Mobil"]
    # Bos hucre None olarak KALIR -- extract_file_dates_by_hash'in aksine
    # ATILMAZ (bkz. fonksiyonun docstring'i).
    assert values_by_target["source"][unique_hash] == [None]
    # Bos metinli satirin hash'i (BosMetinSatiri degeri) hic gorunmez.
    assert len(values_by_target["source"]) == 2


def test_extract_file_column_values_by_hash_multiple_targets_stay_aligned(
    tmp_path: Path,
) -> None:
    """Aynı satırın FARKLI hedefler için çıkardığı değerler aynı
    POZİSYONDA kalmalı — iki hedefin i'inci elemanı hep aynı dosya
    satırına ait olmalı."""
    path = tmp_path / "multi-target.csv"
    _write_csv(
        path,
        [
            ["yorum", "kaynak", "kanal"],
            ["tekrar eden yorum", "Website", "Mobil"],
            ["tekrar eden yorum", "", "Web"],
        ],
    )
    values_by_target = backfill.extract_file_column_values_by_hash(
        path,
        text_column="yorum",
        value_columns={"source": "kaynak", "channel": "kanal"},
    )
    from imga_core.text_utils import review_text_hash

    h = review_text_hash("tekrar eden yorum")
    assert values_by_target["source"][h] == ["Website", None]
    assert values_by_target["channel"][h] == ["Mobil", "Web"]


def test_extract_file_column_values_by_hash_raises_on_missing_value_header(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing-header.csv"
    _write_csv(path, [["yorum", "kaynak"], ["bir yorum", "Website"]])
    with pytest.raises(backfill.UnknownColumnError):
        backfill.extract_file_column_values_by_hash(
            path, text_column="yorum", value_columns={"source": "Kaynak Yok"}
        )


def test_extract_file_column_values_by_hash_raises_on_missing_text_column(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing-text.csv"
    _write_csv(path, [["yorum", "kaynak"], ["bir yorum", "Website"]])
    with pytest.raises(backfill.UnknownColumnError):
        backfill.extract_file_column_values_by_hash(
            path, text_column="olmayan-kolon", value_columns={"source": "kaynak"}
        )


def test_extract_file_column_values_by_hash_reads_xlsx(tmp_path: Path) -> None:
    from imga_core.text_utils import review_text_hash
    from openpyxl import Workbook

    path = tmp_path / "backfill-source.xlsx"
    wb = Workbook()
    sheet = wb.active
    assert sheet is not None
    sheet.append(["yorum", "kaynak"])
    sheet.append(["tekil yorum", "Website"])
    sheet.append(["tekil yorum 2", None])  # bos hucre -> None
    wb.save(path)

    values_by_target = backfill.extract_file_column_values_by_hash(
        path, text_column="yorum", value_columns={"source": "kaynak"}
    )
    h1 = review_text_hash("tekil yorum")
    h2 = review_text_hash("tekil yorum 2")
    assert values_by_target["source"][h1] == ["Website"]
    assert values_by_target["source"][h2] == [None]
