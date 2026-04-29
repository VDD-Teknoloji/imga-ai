# imga-core

Turkish customer-review sentiment analysis pipeline.

Combines a Turkish BERT classifier (`savasy/bert-base-turkish-sentiment-cased`) with
deterministic override layers (critical keywords, strong-negative adjectives, SLA
detection, operational fallbacks) and a learned knowledge base of corrected labels.

This package is the headless core extracted from the legacy Streamlit prototype
(`legacy/app.py`). It contains no UI code.

## Install

```bash
pip install -e "packages/imga-core[dev]"
```

Python 3.11+ required. CPU torch is sufficient.

## Usage

```python
from imga_core import AnalysisPipeline, BertSentimentAnalyzer

pipeline = AnalysisPipeline(analyzer=BertSentimentAnalyzer())
result = pipeline.analyze("Kargom 5 gündür gelmedi, rezalet bir hizmet.")

print(result.sentiment_label)   # "NEGATIF"
print(result.sentiment_score)   # -0.75
print(result.overrides_applied) # [OverrideHit(layer="tier1", ...)]
```

Batch:

```python
results = pipeline.analyze_batch(["...", "...", "..."])
```

With knowledge-base persistence (corrected labels):

```python
pipeline = AnalysisPipeline(
    analyzer=BertSentimentAnalyzer(),
    knowledge_base_path="path/to/training_data.csv",
)
```

## Pipeline order

For each input text, in order:

1. **Knowledge base** — exact-match lookup of corrected labels
2. **Critical override** — security/legal keyword detection (-0.95)
3. **Tier-1 override** — strong-negative adjectives (-0.75)
4. **BERT inference** — only if no override fired
5. **SLA detection** — duration regex against shipping/warehouse limits
6. **Tier-2 fallback** — operational keywords if BERT missed negativity

## Test

```bash
pytest packages/imga-core/tests
```

Snapshot tests (`-m slow`) require the BERT model (~450MB) to be downloaded on
first run and are skipped by default unless fixtures are present.
