"""Resolve filesystem paths for persisted user files (rules, KB)."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_DIR = Path(os.environ.get("IMGA_DATA_PATH", "./data"))


def data_dir() -> Path:
    d = DEFAULT_DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def rules_path() -> Path:
    return data_dir() / "cx_rules.json"


def params_path() -> Path:
    return data_dir() / "cx_params.json"


def training_data_path() -> Path:
    return data_dir() / "training_data.csv"
