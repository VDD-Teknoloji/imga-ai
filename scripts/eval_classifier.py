"""4 eksenli sınıflandırıcı değerlendirmesi — ÜRETİM yolu üzerinden.

Referans setini (duygu, skor bandı, kategori, deneyim) gerçek üretim
sınıflandırıcısıyla (gerçek kimlik + taksonomi payload'ı + parse)
koşturur; her prompt/model değişikliği canlıya çıkmadan önce burada
puanlanır. api konteyneri içinde çalışır:

    docker exec imga-prod-api python /tmp/eval_classifier.py \
        /tmp/gold4.csv [--prompt-file /tmp/aday_prompt.txt] [--tenant "Navlungo Test"]

Çıktı: eksen bazında doğruluk + karışıklık + /tmp/eval4_out.csv.
2026-08-10 hedef çalışması — kalıcı regresyon kapısı.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from collections import Counter

SC_BANDS: tuple[tuple[float, float, str], ...] = (
    (-1.01, -0.65, "guclu_neg"),
    (-0.65, -0.35, "orta_neg"),
    (-0.35, -0.07, "hafif_neg"),
    (-0.07, 0.07, "notr"),
    (0.07, 0.35, "hafif_poz"),
    (0.35, 0.65, "orta_poz"),
    (0.65, 1.01, "guclu_poz"),
)


def band_of(score: float) -> str:
    for lo, hi, name in SC_BANDS:
        if lo <= score < hi:
            return name
    return "guclu_poz"


def band_distance(a: str, b: str) -> int:
    order = [name for _, _, name in SC_BANDS]
    return abs(order.index(a) - order.index(b))


async def main() -> None:
    from imga_core.categories.taxonomy import (
        CATEGORY_DESCRIPTIONS_TR,
        GLOBAL_CATEGORY_CODES,
    )
    from imga_core.llm.unified_classifier import GeminiUnifiedEngine
    from imga_db import create_engine, create_session_factory
    from imga_db.session import set_current_tenant
    from sqlalchemy import text as sql_text

    from imga_api.services.llm_credentials import load_active_llm_keys
    from imga_api.services.llm_provider_factory import resolve_model_name
    from imga_api.workers.batch_analyzer import _load_taxonomy_payload

    ap = argparse.ArgumentParser()
    ap.add_argument("gold_csv")
    ap.add_argument("--prompt-file", default=None)
    ap.add_argument("--tenant", default="Navlungo Test")
    ap.add_argument("--out", default="/tmp/eval4_out.csv")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.gold_csv, encoding="utf-8")))
    print(f"referans: {len(rows)} satir", flush=True)

    system_prompt: str | None = None
    if args.prompt_file:
        system_prompt = open(args.prompt_file, encoding="utf-8").read()
        print(f"aday prompt: {args.prompt_file} ({len(system_prompt)} kr)", flush=True)

    engine = create_engine("admin")
    factory = create_session_factory(engine)
    async with factory() as session:
        tid = (
            await session.execute(
                sql_text("SELECT id FROM tenants WHERE name = :n"),
                {"n": args.tenant},
            )
        ).scalar_one()
        await set_current_tenant(session, tid)
        selection = await load_active_llm_keys(session, tid)
        snapshot = await _load_taxonomy_payload(session, tid)
    await engine.dispose()
    assert selection is not None, "aktif LLM kimligi yok"

    model = resolve_model_name(selection.provider, selection.model)
    print(f"model: {selection.provider}/{model}", flush=True)

    ue = GeminiUnifiedEngine(
        selection.keys,
        model_name=model,
        concurrency=4,
        provider=selection.provider,
        system_prompt=system_prompt,
    )
    preds, stats = await ue.classify_unified_batch_async(
        [r["text"] for r in rows],
        available_categories=list(GLOBAL_CATEGORY_CODES),
        perspective_options=snapshot.perspective_options,
        category_descriptions=CATEGORY_DESCRIPTIONS_TR,
    )

    s_hit = c_hit = e_hit = e_total = band_exact = band_adjacent = 0
    belirsiz = 0
    s_conf: Counter[tuple[str, str]] = Counter()
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["id", "gold_s", "pred_s", "gold_sc", "pred_sc",
             "gold_c", "pred_c", "gold_e", "pred_e"]
        )
        for r, p in zip(rows, preds):
            gs, gc = r["s"], r["c"]
            ge = (r.get("e") or "").strip()
            gsc = float(r["sc"])
            pe = getattr(p, "experience_type", None) or ""
            s_conf[(gs, p.sentiment_label)] += 1
            s_hit += p.sentiment_label == gs
            c_hit += p.category == gc
            if p.category == "belirsiz":
                belirsiz += 1
            d = band_distance(band_of(gsc), band_of(p.sentiment_score))
            band_exact += d == 0
            band_adjacent += d <= 1
            if ge:
                e_total += 1
                e_hit += pe == ge
            w.writerow(
                [r["id"], gs, p.sentiment_label, f"{gsc:.2f}",
                 f"{p.sentiment_score:.2f}", gc, p.category, ge, pe]
            )

    n = len(rows)
    print(f"DUYGU     : {s_hit}/{n} = {s_hit / n:.3f}", flush=True)
    print(
        f"SKOR BANDI: ayni={band_exact / n:.3f} "
        f"komsu-dahil={band_adjacent / n:.3f}",
        flush=True,
    )
    print(f"KATEGORI  : {c_hit}/{n} = {c_hit / n:.3f} "
          f"(belirsiz orani {belirsiz / n:.3f})", flush=True)
    if e_total:
        print(f"DENEYIM   : {e_hit}/{e_total} = {e_hit / e_total:.3f}", flush=True)
    else:
        print("DENEYIM   : referans yok / model e uretmiyor", flush=True)
    print("duygu karisikligi (gold -> pred):", flush=True)
    for (g, p_), cnt in sorted(s_conf.items()):
        print(f"  {g:8s} -> {p_:8s}: {cnt}", flush=True)
    print(
        f"calls={stats.calls} in={stats.input_tokens} out={stats.output_tokens}",
        flush=True,
    )
    print("EVAL4_OK", flush=True)


asyncio.run(main())
