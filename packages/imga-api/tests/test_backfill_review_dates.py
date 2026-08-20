"""Unit tests for scripts/backfill_review_dates.py's pure logic.

``scripts/`` has no ``__init__.py`` — it's not an importable package —
so the script is loaded via ``importlib.util.spec_from_file_location``
rather than a normal ``import``. Only the SAF (pure, I/O-less) functions
(``match_dates_by_hash_order``, ``safety_check``) and the file-reading
helper (``extract_file_dates_by_hash``, exercised against real temp
files) are covered here — no DB, mirrors test_file_parser.py's "runs
without a DB" scope. The DB round-trip (``fetch_db_rows_by_hash``,
``_apply_updates``, ``run()``) needs live Postgres and is out of scope
for this file; it's covered by manual --dry-run verification per the
script's own docstring.
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
    candidates = [
        parent / "scripts" / "backfill_review_dates.py"
        for parent in here.parents
    ]
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
    spec = importlib.util.spec_from_file_location(
        "backfill_review_dates", _SCRIPT_PATH
    )
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
