"""User-defined Smart Rules engine for perspective classification.

Reads the legacy cx_rules.json format::

    {
      "customer_rules": [
        {"keywords": ["online değişim"], "label": "Dijital Eksiklik Talebi"}
      ],
      "company_rules": [
        {"keywords": ["stok hatası"], "label": "Stok Yönetimi"}
      ]
    }

Rules are tried in declaration order; the first one whose ANY keyword matches
the lowercased text wins. They run BEFORE the hard-coded heuristics in
`perspectives.py` — both functions return ``None`` when no rule matches, so
the caller can fall through.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Rule:
    """A single user-defined rule: any keyword match -> assign label."""

    keywords: tuple[str, ...]
    label: str

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Rule:
        raw_keywords = data.get("keywords", [])
        if not isinstance(raw_keywords, list):
            raise ValueError(f"keywords must be a list, got {type(raw_keywords).__name__}")
        label = data.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label must be a non-empty string")
        return cls(
            keywords=tuple(str(k).strip().lower() for k in raw_keywords if str(k).strip()),
            label=label,
        )

    def matches(self, lowered_text: str) -> bool:
        return any(kw in lowered_text for kw in self.keywords)


@dataclass(frozen=True, slots=True)
class RuleSet:
    """A pair of customer-side and company-side rule lists."""

    customer_rules: tuple[Rule, ...] = field(default_factory=tuple)
    company_rules: tuple[Rule, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not self.customer_rules and not self.company_rules


class RuleEngine:
    """Loads a RuleSet from disk and provides classify_* lookups.

    Constructor injection: pass a path or None. None disables the engine
    cleanly without changing call sites.
    """

    def __init__(self, rules_path: Path | str | None) -> None:
        self._path = Path(rules_path) if rules_path else None
        self._ruleset = self._load()

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def ruleset(self) -> RuleSet:
        return self._ruleset

    def classify_customer(self, text: str) -> str | None:
        """Return the first matching customer label, or None."""
        return self._classify(text, self._ruleset.customer_rules)

    def classify_company(self, text: str) -> str | None:
        """Return the first matching company label, or None."""
        return self._classify(text, self._ruleset.company_rules)

    def _classify(self, text: str, rules: tuple[Rule, ...]) -> str | None:
        if not text or not rules:
            return None
        lowered = text.lower()
        for rule in rules:
            if rule.matches(lowered):
                return rule.label
        return None

    def _load(self) -> RuleSet:
        if self._path is None:
            return RuleSet()
        if not self._path.exists():
            _logger.info("Smart Rules path not found: %s", self._path)
            return RuleSet()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _logger.warning("Failed to read Smart Rules from %s: %s", self._path, exc)
            return RuleSet()

        return RuleSet(
            customer_rules=_parse_rules(payload.get("customer_rules", [])),
            company_rules=_parse_rules(payload.get("company_rules", [])),
        )


def _parse_rules(raw: object) -> tuple[Rule, ...]:
    if not isinstance(raw, list):
        return ()
    parsed: list[Rule] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(Rule.from_dict(item))
        except ValueError as exc:
            _logger.warning("Skipping malformed rule %r: %s", item, exc)
    return tuple(parsed)
