"""Smoke tests for services that don't require Streamlit runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from imga_dashboard import services


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "rules_path", lambda: tmp_path / "cx_rules.json")
    monkeypatch.setattr(services, "params_path", lambda: tmp_path / "cx_params.json")
    monkeypatch.setattr(services, "training_data_path", lambda: tmp_path / "training.csv")


def test_detect_text_column_finds_known_column() -> None:
    df = pd.DataFrame({"Müşteri Yorumu": ["a"], "Other": ["b"]})
    assert services.detect_text_column(df) == "Müşteri Yorumu"


def test_detect_text_column_returns_none_when_absent() -> None:
    df = pd.DataFrame({"foo": ["a"]})
    assert services.detect_text_column(df) is None


def test_load_params_returns_defaults_when_missing() -> None:
    p = services.load_params()
    assert p["max_shipping_days"] == 3
    assert p["max_warehouse_days"] == 2


def test_save_and_load_params_roundtrip(tmp_path: Path) -> None:
    services.save_params({"max_shipping_days": 7, "max_warehouse_days": 4})
    loaded = services.load_params()
    assert loaded["max_shipping_days"] == 7
    assert loaded["max_warehouse_days"] == 4


def test_load_rules_returns_empty_when_missing() -> None:
    r = services.load_rules()
    assert r == {"customer_rules": [], "company_rules": []}


def test_save_and_load_rules_roundtrip() -> None:
    payload = {
        "customer_rules": [{"keywords": ["foo"], "label": "Bar"}],
        "company_rules": [],
    }
    services.save_rules(payload)
    loaded = services.load_rules()
    assert loaded == payload
    # Sanity: file is utf-8 readable JSON
    raw = services.rules_path().read_text(encoding="utf-8")
    assert "Bar" in raw and json.loads(raw) == payload


def test_load_rules_handles_corrupt_file() -> None:
    services.rules_path().write_text("{bad json", encoding="utf-8")
    r = services.load_rules()
    assert r == {"customer_rules": [], "company_rules": []}
