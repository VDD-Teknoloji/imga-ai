"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from imga_core.config import (
    DEFAULT_BERT_MODEL,
    DEFAULT_MAX_SHIPPING_DAYS,
    DEFAULT_MAX_WAREHOUSE_DAYS,
)


@dataclass(frozen=True, slots=True)
class Settings:
    bert_model: str = DEFAULT_BERT_MODEL
    knowledge_base_path: Path | None = None
    rules_path: Path | None = None
    max_shipping_days: int = DEFAULT_MAX_SHIPPING_DAYS
    max_warehouse_days: int = DEFAULT_MAX_WAREHOUSE_DAYS

    @classmethod
    def from_env(cls) -> Settings:
        def _opt_path(name: str) -> Path | None:
            raw = os.environ.get(name)
            return Path(raw) if raw else None

        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        return cls(
            bert_model=os.environ.get("IMGA_BERT_MODEL", DEFAULT_BERT_MODEL),
            knowledge_base_path=_opt_path("IMGA_KB_PATH"),
            rules_path=_opt_path("IMGA_RULES_PATH"),
            max_shipping_days=_int("IMGA_MAX_SHIPPING_DAYS", DEFAULT_MAX_SHIPPING_DAYS),
            max_warehouse_days=_int("IMGA_MAX_WAREHOUSE_DAYS", DEFAULT_MAX_WAREHOUSE_DAYS),
        )
