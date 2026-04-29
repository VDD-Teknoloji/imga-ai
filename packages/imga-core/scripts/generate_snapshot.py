"""Calibrate tests/fixtures/snapshot_inputs.json against the live pipeline.

For every BERT-required case, runs the actual pipeline (loads the BERT model
on first call) and replaces the score range / placeholder with the observed
score, rounded to 2 decimals. Override-only cases are left untouched.

Usage:
    python scripts/generate_snapshot.py --dry-run
    python scripts/generate_snapshot.py --in tests/fixtures/snapshot_inputs.json \\
                                        --out tests/fixtures/snapshot_calibrated.json

The output file is intentionally separate so a regenerated snapshot can be
diffed and reviewed before being promoted over the canonical fixtures.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("snapshot-cal")

DEFAULT_IN = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "snapshot_inputs.json"
DEFAULT_OUT = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "snapshot_calibrated.json"
)


def calibrate(
    cases: list[dict[str, Any]], pipeline_factory: Any, dry_run: bool
) -> list[dict[str, Any]]:
    needs_bert = [c for c in cases if c.get("bert_required", True)]
    log.info("Cases: %d total, %d BERT-required", len(cases), len(needs_bert))

    if not needs_bert or dry_run:
        if dry_run:
            log.info("Dry-run: skipping pipeline construction")
        return cases

    pipeline = pipeline_factory()
    texts = [c["text"] for c in needs_bert]
    log.info("Running pipeline.analyze_batch on %d texts", len(texts))
    results = pipeline.analyze_batch(texts)

    by_id = {c["id"]: c for c in cases}
    for case, result in zip(needs_bert, results, strict=True):
        cid = case["id"]
        observed = round(float(result.sentiment_score), 2)
        observed_label = result.sentiment_label
        log.info(
            "  [%s] label=%s score=%s -> %s",
            cid,
            observed_label,
            observed,
            "calibrated",
        )
        merged = dict(case)
        merged.pop("expected_score_min", None)
        merged.pop("expected_score_max", None)
        merged["expected_label"] = observed_label
        merged["expected_score"] = observed
        by_id[cid] = merged

    return list(by_id.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", type=Path, default=DEFAULT_IN)
    parser.add_argument("--out", dest="dst", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse fixtures and report counts; do not load BERT or write output.",
    )
    args = parser.parse_args(argv)

    if not args.src.exists():
        log.error("Input fixture not found: %s", args.src)
        return 1

    payload = json.loads(args.src.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = payload.get("cases", [])
    if not cases:
        log.error("No cases in %s", args.src)
        return 1

    def build_pipeline() -> Any:  # imports kept local so --dry-run avoids torch
        from imga_core import AnalysisPipeline, BertSentimentAnalyzer

        log.info("Loading BERT pipeline (first call may download ~450MB)...")
        return AnalysisPipeline(analyzer=BertSentimentAnalyzer())

    new_cases = calibrate(cases, build_pipeline, dry_run=args.dry_run)
    payload["cases"] = new_cases
    payload.setdefault("_meta", {})["calibrated"] = not args.dry_run

    if args.dry_run:
        log.info("Dry-run finished. Would have written %d cases to %s", len(new_cases), args.dst)
        return 0

    args.dst.parent.mkdir(parents=True, exist_ok=True)
    args.dst.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log.info("Wrote %d cases to %s", len(new_cases), args.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
