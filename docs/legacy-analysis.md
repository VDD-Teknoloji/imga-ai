# legacy/app.py — Code Review (snapshot @ 2026-04-29)

> Snapshot of the code-quality assessment that motivated the imga-core extraction.
> Source file: `legacy/app.py` (732 lines, monolithic Streamlit prototype).

## 1. One-line summary

A 732-line single-file Streamlit prototype that runs Turkish customer reviews
through a local BERT classifier plus hard-coded Turkish lexicons; functionally
correct but architecturally monolithic and full of duplication.

## 2. Stack & dependencies

- **Python**: not pinned anywhere (no `requirements.txt`, no `pyproject.toml`).
- **Libraries**: `streamlit`, `pandas`, `transformers`, `torch`, `plotly`
  (imported but unused), plus stdlib (`re`, `io`, `concurrent.futures`,
  `time` — these last three are also unused).
- **AI provider**: fully local. HuggingFace pipeline downloads
  `savasy/bert-base-turkish-sentiment-cased` on first run. No external LLM API.
- **Framework**: Streamlit. No HTTP endpoints.

## 3. Workflow

User uploads `.xlsx`/`.csv` from the sidebar; a column named `Müşteri Yorumu`
or `Review` is auto-detected. Each row passes through an override chain
(Knowledge Base → CRITICAL keywords → TIER1 sentiment) before BERT inference.
After BERT, an SLA regex (`(\d+)\s*(?:gün|iş günü|hafta)`) and a TIER2
operational fallback adjust the score. Outputs feed an executive panel
(SHI, crisis count, top-3 bottlenecks). A correction loop appends user fixes
to `training_data.csv`, growing the knowledge base.

## 4. External dependencies

- **API calls**: none. Fully local model.
- **HuggingFace Hub**: model download only.
- **CDN**: a sidebar logo PNG from `cdn-icons-png.flaticon.com`.
- **Auth / credentials**: none required, none stored.

## 5. Code-quality summary

| Criterion | State | Note |
|---|---|---|
| Type hints | None | No parameter or return type anywhere. |
| Docstrings | None | Only `# --- Section ---` markers, mixed TR/EN. |
| Error handling | Weak | `except: pass` at line 144, two more bare excepts (186, 199). |
| Logging | None | Uses `st.error`/`st.success`; no server-side trace. |
| Tests | None | No test file exists. |
| Structure | Monolithic | 732 lines, UI + logic + persistence + ML in one file. |
| Duplication | Heavy | Customer/company perspectives, load/save rules/params, target-col detection (3×). |

- **Total lines**: 732
- **Functions**: 11 top-level + 4 nested = 15
- **Longest function**: `process_dataframe`, lines 210–460 (~250 lines)

## 6. Red flags

- **Hard-coded credentials**: none (no credentials needed).
- **Security**: `unsafe_allow_html=True` (line 59) used only for static CSS;
  uploaded files go straight into `pd.read_excel`/`pd.read_csv` with no size
  limit (DoS risk if exposed publicly).
- **Performance**:
  - `@st.cache_data(show_spinner=False)` is **stacked three times**
    (lines 207–209) on `process_dataframe` — a copy-paste bug.
  - `process_dataframe` cached but takes a large `df` as input — Streamlit
    has to hash the full DataFrame on every call.
  - `cx_rules.json`, `cx_params.json`, `training_data.csv` re-read from disk
    on every Streamlit rerun (every UI interaction).
- **Logic bugs**:
  - `get_customer_perspective` (line 315) is **defined but never called**.
    The `Müşteri Perspektifi` column is referenced at line 470 but never
    populated — silently absent in the UI.
  - Knowledge-base lookup at line 371–373 mixes `t_str` (string-coerced) for
    the `in` check with the original `text` for dict access — `KeyError`
    possible on non-string inputs.
  - `Subjectivity` is always 0.0 — dead column.
  - Three consecutive `st.markdown("---")` calls in the sidebar
    (lines 168, 172, 175) — cosmetic bug.
- **Dead code / unused imports**: `plotly.express as px`, `io`, `torch`
  (explicit), `concurrent.futures`, `time`.

## 7. Top-3 problems

1. **`process_dataframe` is a 250-line god-function** — untestable, hard to
   debug, mixes lexicons, override chain, BERT batching, SLA regex, and
   Tier-2 fallback. Splitting this is the prerequisite for everything else.
2. **`get_customer_perspective` is defined but never called** — this is a
   missing feature, not just dead code. The UI claims `Müşteri Perspektifi`
   exists but the column is never written to the DataFrame.
3. **No `requirements.txt`, no version pins** — `transformers`/`torch`
   majors break compatibility regularly; the project isn't reproducible on
   another machine until this is fixed.

## 8. Rewrite vs. refactor

Refactor wins. The logic is correct: BERT pipeline is wired right, override
layers are sensible, the SLA regex works, the knowledge-base feedback loop is
clever. The problem is **organization**: monolithic file, magic numbers
inline, no types, no tests. Splitting `process_dataframe` into a layered
override chain, lifting the lexicons into module-level constants, and adding
type hints + a snapshot test gets us a clean package in 1–2 days. A full
rewrite risks losing accumulated Turkish-domain knowledge embedded in the
hand-tuned lexicons. The new package (`packages/imga-core`) is exactly that
refactor done as a parallel build, so the legacy file can stay as a
behavioral reference until parity is verified.
