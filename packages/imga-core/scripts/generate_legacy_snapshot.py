"""Run legacy/app.py against the fixture inputs and dump the actual outputs.

Strategy: streamlit is mocked out (sys.modules['streamlit'] = passthrough mock),
legacy/app.py is imported, and `process_dataframe` is invoked directly with a
DataFrame. The mock turns @st.cache_data / @st.cache_resource decorators into
no-ops, prevents file_uploader from triggering the upload branch at module
top-level, and makes session_state a plain dict so 'in' works.

Output: tests/fixtures/legacy_snapshot.json with one entry per fixture,
containing the actual sentiment_label, sentiment_score, summary, and
perspectives that legacy/app.py produced for that text.

Usage:
    python scripts/generate_legacy_snapshot.py
    python scripts/generate_legacy_snapshot.py --limit 5    # quick test

The first run downloads ~450MB BERT model unless HF_HOME cache is populated.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("legacy-snapshot")

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_DIR = REPO_ROOT / "legacy"
FIXTURE_IN = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "snapshot_inputs.json"
)
FIXTURE_OUT = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "legacy_snapshot.json"
)


class _PassthroughDecorator:
    """Replacement for @st.cache_data / @st.cache_resource.

    Supports both bare-decorator and parametrized-decorator usage:
        @st.cache_data
        def f(): ...

        @st.cache_data(show_spinner=False)
        def f(): ...
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if args and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f


class _StreamlitMock(MagicMock):
    """A MagicMock that knows how to unpack tabs/columns into N MagicMocks."""

    def tabs(self, names: Any) -> tuple[MagicMock, ...]:
        return tuple(MagicMock() for _ in names)

    def columns(self, n: Any) -> tuple[MagicMock, ...]:
        if isinstance(n, int):
            return tuple(MagicMock() for _ in range(n))
        return tuple(MagicMock() for _ in n)


def _install_streamlit_mock() -> None:
    """Make `import streamlit as st` work without a real streamlit install.

    Sentinels are tuned so the upload, form-submit, and button branches in
    the top-level legacy code do NOT fire — otherwise legacy attempts to call
    save_rules(...) with a MagicMock value, which is not JSON-serializable.
    """
    st = _StreamlitMock()
    st.cache_data = _PassthroughDecorator()
    st.cache_resource = _PassthroughDecorator()
    st.session_state = {}
    # Branch-killing returns:
    st.file_uploader = lambda *a, **k: None
    st.button = lambda *a, **k: False
    st.form_submit_button = lambda *a, **k: False
    st.text_input = lambda *a, **k: ""
    st.text_area = lambda *a, **k: ""
    st.selectbox = lambda *a, **k: (k.get("options") or ["All"])[0]
    st.checkbox = lambda *a, **k: False
    st.number_input = lambda *a, **k: int(k.get("value", 0) or 0)
    # Spinner / form / sidebar are context managers; MagicMock supports that.
    sys.modules["streamlit"] = st


def _import_legacy_app() -> Any:
    """Import legacy/app.py with side-effects sandboxed to a tmp dir.

    Legacy uses CWD-relative paths for cx_rules.json / cx_params.json /
    training_data.csv. Any branch we fail to mock might write files there;
    chdir to a tmp dir so accidental writes don't leak into the repo.
    """
    import os
    import tempfile

    sandbox = Path(tempfile.mkdtemp(prefix="legacy_snapshot_sandbox_"))
    os.chdir(sandbox)

    _install_streamlit_mock()
    sys.path.insert(0, str(LEGACY_DIR))
    import importlib

    if "app" in sys.modules:
        del sys.modules["app"]
    return importlib.import_module("app")


def _run_legacy(texts: list[str]) -> list[dict[str, Any]]:
    import pandas as pd

    legacy = _import_legacy_app()
    df = pd.DataFrame({"Müşteri Yorumu": texts})
    rules = {"customer_rules": [], "company_rules": []}
    knowledge_base: dict[str, str] = {}
    params = {"max_shipping_days": 3, "max_warehouse_days": 2}

    log.info("Calling legacy.process_dataframe on %d texts", len(texts))
    out_df = legacy.process_dataframe(df, "Müşteri Yorumu", rules, knowledge_base, params)
    log.info("Legacy returned columns: %s", list(out_df.columns))

    # Restore original input order: legacy sorts by score ascending.
    out_df = out_df.set_index("Müşteri Yorumu").reindex(texts).reset_index()

    rows: list[dict[str, Any]] = []
    for _, row in out_df.iterrows():
        rows.append(
            {
                "text": row["Müşteri Yorumu"],
                "legacy_label": row.get("Sentiment_Label"),
                "legacy_score": (
                    float(row["Sentiment_Score"])
                    if row.get("Sentiment_Score") is not None
                    else None
                ),
                "legacy_summary": row.get("Yorum Özet"),
                "legacy_company_perspective": row.get("Şirket Perspektifi"),
                "legacy_risk": row.get("Risk Durumu"),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=FIXTURE_IN)
    p.add_argument("--output", type=Path, default=FIXTURE_OUT)
    p.add_argument("--limit", type=int, default=0, help="Process only first N cases")
    args = p.parse_args(argv)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    if args.limit:
        cases = cases[: args.limit]
    log.info("Loaded %d input cases", len(cases))

    texts = [c["text"] for c in cases]
    legacy_rows = _run_legacy(texts)

    # Stitch case ids back so the output is keyed by id.
    out: list[dict[str, Any]] = []
    for case, legacy in zip(cases, legacy_rows, strict=True):
        merged = {
            "id": case["id"],
            **legacy,
            "input_meta": {k: v for k, v in case.items() if k not in {"text"}},
        }
        out.append(merged)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"cases": out}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log.info("Wrote %d cases to %s", len(out), args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
