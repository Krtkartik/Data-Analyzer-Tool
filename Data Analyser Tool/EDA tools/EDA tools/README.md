# Smart Data Quality Analyzer & Automated EDA Tool

**Version 1.0.0** · Python 3 + Streamlit · ~3,500 lines across 11 modules

An end-to-end data quality and exploratory analysis application. Drop in a CSV /
XLSX / JSON file and the app walks it through a complete eight-stage pipeline —
loading, profiling, quality diagnosis, interactive cleaning, automated EDA,
plain-language insights, a 0–100 quality score, and a downloadable report.

Everything is built from scratch: no profiling shortcuts, no black-box profiler,
no notebook. Each stage is a plain Python module with typed dataclasses as its
return contract, so the whole thing runs headless in a script or as pytest cases
just as well as it runs in the browser.

---

## Table of contents

1. [Why this app exists](#1-why-this-app-exists)
2. [Quick start](#2-quick-start)
3. [Feature tour](#3-feature-tour)
4. [The eight-stage pipeline](#4-the-eight-stage-pipeline)
5. [Scoring model](#5-scoring-model)
6. [Architecture](#6-architecture)
7. [Programmatic (headless) usage](#7-programmatic-headless-usage)
8. [Bundled sample datasets](#8-bundled-sample-datasets)
9. [Configuration reference](#9-configuration-reference)
10. [Testing](#10-testing)
11. [Work completed](#11-work-completed)
12. [Design decisions](#12-design-decisions)
13. [Known limitations](#13-known-limitations)
14. [Future work](#14-future-work)

---

## 1. Why this app exists

Exploratory data analysis is usually a manual loop: open a notebook, print
shapes, eyeball dtypes, hand-write missing-value counts, guess at outliers,
draw three charts, then start again on the next file. It is slow, it is not
reproducible, and the findings never leave the notebook.

This app turns that loop into a repeatable pipeline with three properties:

| Property | How it is achieved |
|---|---|
| **Grounded** | Every number is computed from the loaded dataframe — no sampling heuristics or mocked statistics, even in the bundled demo datasets |
| **Explainable** | Column types come with the evidence that produced them; the score is decomposed into five named dimensions; every cleaning step is written to an audit log |
| **Auditable** | The cleaning log, quality score before/after, and the full report are all downloadable |

---

## 2. Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open the printed URL (default <http://localhost:8501>). No data to hand? The
**Upload** tab ships three generated sample datasets — pick one from the
dropdown and press *Load sample*.

Run the test suite:

```bash
python tests/test_pipeline.py
```

---

## 3. Feature tour

| | Feature | Where |
|---|---|---|
| **Ingestion** | CSV / TSV / TXT / XLSX / XLS / JSON | `load.py` |
| | Encoding auto-detection (chardet, with latin-1 / cp1252 / utf-16 fallback ladder) | `load.py:38` |
| | Delimiter auto-detection (`,` `;` `\t` `\|`) | `load.py:54` |
| | Lazy chunked reading, capped at 200,000 analysed rows | `load.py:90` |
| **Profiling** | Shape, memory footprint, per-column count/unique/missing | `profile.py:155` |
| | Column-type classification into numerical / categorical / datetime / text / boolean, each with a confidence score and human-readable reasons | `profile.py:66` |
| | Full summary-statistics table (mean, std, min, max, skew, kurtosis, first, last) | `profile.py:205` |
| **Quality** | Missing-value report + Plotly missingness heatmap | `quality.py:43`, `quality.py:62` |
| | Duplicate detection with before/after previews | `quality.py:93` |
| | Type-consistency checks (text hiding inside numeric / datetime columns) | `quality.py:110` |
| | Outlier detection by **IQR** (1.5×) and **Z-score** (3σ), with per-column bounds | `quality.py:175` |
| | Categorical analysis: cardinality ratio, top values, rare categories (<1%), inconsistent labels | `quality.py:265` |
| | Validation rules: email regex, phone regex, ID uniqueness, implied value range, negative values, future dates, `start ≤ end` cross-column pairs | `quality.py:339`, `quality.py:431` |
| **Cleaning** | 7 imputation strategies per column | `clean.py:84` |
| | Duplicate removal with optional subset | `clean.py:124` |
| | Dtype auto-correction (string → numeric / datetime / bool / category) | `clean.py:133` |
| | Categorical label standardisation: strip, case-fold, fuzzy-merge via rapidfuzz | `clean.py:179` |
| | Outlier strategies: flag / cap (winsorize) / remove | `clean.py:253` |
| | Timestamped audit log of every action | `clean.py:48` |
| **EDA** | Per-column distribution shape labels (normal / skewed / heavy-tailed / long-tail / dominated / constant) | `eda.py:93` |
| | Freedman–Diaconis optimal histogram binning | `eda.py:110` |
| | Bivariate discovery: Pearson correlation, Eta (num↔cat), Cramér's V (cat↔cat) | `eda.py:153` |
| | Correlation matrix + strong-relationship ranking | `eda.py:295` |
| **Charts** | 12 chart builders + an automatic chart-selection engine with reasons | `visualize.py` |
| **Insights** | Rule-based natural-language findings, sorted by severity | `insights.py:235` |
| **Score** | 0–100 across five weighted dimensions, letter grade, before/after delta | `score.py:148` |
| **Report** | HTML report, PDF report (reportlab, landscape A4), cleaned CSV, cleaning log CSV | `report.py` |

---

## 4. The eight-stage pipeline

```
Upload ──▶ Profile ──▶ Quality ──▶ Cleaning ──▶ EDA ──▶ Insights ──▶ Score ──▶ Report
```

The sidebar radio selects one stage at a time; a progress line at the bottom of
the page shows which stages have already been computed. Each stage is memoised
in `st.session_state` and invalidated when the data changes, so switching tabs
never re-runs a slow computation.

### Stage 1 — Upload

`load_dataset(uploaded)` returns a `LoadResult` dataclass:

```python
LoadResult(
    df=pd.DataFrame, file_name=str, file_type="csv"|"xlsx"|"json",
    encoding=str|None, delimiter=str|None,
    truncated=bool, original_rows=int, chunk_count=int, messages=list,
)
```

- **Encoding** — `chardet` over the first 100 KB; accepted above 0.6 confidence,
  then validated by actually decoding the bytes. Falls back through
  `utf-8 → cp1252 → latin-1 → utf-16` and finally a lossy latin-1 read.
- **Delimiter** — counts candidates in the header line, most frequent wins.
- **Large files** — CSV is read with `chunksize=50_000` and the loop breaks as
  soon as 200,000 rows are collected, so a 5 GB file never lands in memory.
  XLSX and JSON are truncated to the same cap after a normal read.
- The app guards on `(file_name, size)` so a Streamlit rerun does not re-parse
  the same file, and shows the detected metadata in a collapsible JSON panel.

### Stage 2 — Profile

`detect_column_types()` classifies each column with a **decision ladder** and
records the evidence for the verdict:

| Order | Test | Result | Confidence |
|---|---|---|---|
| 1 | bool dtype, or ≤2 distinct values all in `{true,yes,y,n,1,0,t,f,…}` | `boolean` | 0.95 |
| 2 | real datetime64 dtype | `datetime` | 1.00 |
| 3 | numeric dtype | `numerical` | 0.95 |
| 4 | column entirely empty | `text` | 0.40 |
| 5 | >75% of values parse as numbers after stripping `,` `$` `%` | `numerical` | 0.75 |
| 6 | >80% of values parse as dates | `datetime` | 0.90 |
| 7 | ≤15 unique values and ≤5% of rows | `categorical` | 0.85 |
| 8 | >100 unique values | `text` | 0.70 |
| 9 | otherwise | `categorical` | 0.80 |

Rule 5 is what catches dirty columns like an `age` field where someone typed
`"abc"` into 20 of 2000 rows — the column stays `numerical`, and the bad cells
are reported by the type-consistency check rather than silently ignored.

`profile_dataset()` then produces a `ProfileResult` with shape, memory usage
(`memory_usage(deep=True)`), dtype counts, duplicated-row count, per-column
missing counts, and the summary-statistics frame. The summary table mixes
numeric statistics, most-frequent value for categoricals, min/max for datetimes,
and true-rate for booleans in a single object-dtype frame so it renders as one
table in the UI.

### Stage 3 — Quality

`run_quality_analysis(df, column_types)` returns a dict with six keys:

```python
{
  "missing":     MissingReport,          # total, overall %, per-column frame, completeness %
  "duplicates":  {count, share, preview, after_shape, deduplicated_preview},
  "type_issues": pd.DataFrame,            # column, detected_as, anomalous_count/share, examples
  "outliers":    List[OutlierResult],     # column, method, bounds, n_outliers, share_pct, indices
  "categorical": {col: CategoryAnalysis}, # cardinality, top values, rare, inconsistent labels
  "validation":  List[ValidationResult],  # column, check, severity, failures, share, examples
}
```

Detection details worth knowing:

- **Outliers** run two methods per numeric column. IQR uses the classic
  `Q1 − 1.5·IQR` / `Q3 + 1.5·IQR` fences; Z-score uses `|z| > 3`. Columns
  with fewer than 6 usable values are skipped. The stored `outlier_idx` array
  is what the cleaning stage later acts on.
- **Inconsistent labels** normalise by lowercasing and collapsing whitespace,
  then group. If one normalised key maps to several raw spellings
  (`north` / `NORTH` / `south `), it is reported with the variants listed.
- **Implied ranges** are derived from the data itself: the 1st–99th percentile
  widened by 10 IQRs. Anything outside that is flagged, which surfaces typos
  without needing a per-dataset schema.
- **Cross-column logic** pairs columns whose names share a stem around
  `start/end` or `from/to` and reports rows where the first is later than the
  second.

The UI splits this stage into six sub-tabs: Missing values, Duplicates, Type
consistency, Outliers, Categorical, Validation.

### Stage 4 — Cleaning

Five numbered control groups drive one call to `run_cleaning()`:

1. **Missing values** — per column, choose `drop`, `mean`, `median`, `mode`,
   `ffill`, `bfill`, or `constant` (with a value box).
2. **Duplicates** — remove, optionally restricted to a chosen column subset.
3. **Data types** — auto-coerce to the detected kinds.
4. **Categorical labels** — strip, lowercase, then fuzzy-merge near-duplicates
   above a similarity threshold (slider, default 88). Clustering is greedy over
   labels sorted by length, so the shortest spelling becomes the canonical
   representative.
5. **Outliers** — `flag` (adds `<column>_is_outlier` boolean columns),
   `cap` (winsorise to the IQR fences), or `remove` (drop the rows).

```python
cleaned, log, stats = run_cleaning(
    df, column_types,
    imputation={"age": "median"}, constants={"tier": "unknown"},
    drop_dups=True, dedup_subset=["order_id"],
    correct_types=True, standardise_cats=True, fuzzy_threshold=88,
    outlier_action="cap",
)
```

Everything runs on a **working copy** — the raw upload is never mutated, and
"Reset analysis" re-runs the pipeline from the original. `log` is a
`CleaningLog` with `to_dataframe()` for the audit-trail table and CSV export;
`stats` is a list of per-action dicts with affected-row counts.

After cleaning, the app re-detects types on the cleaned frame, recomputes the
quality analysis, and records the new score so the Score tab can show the
improvement.

### Stage 5 — EDA

Four sub-tabs:

- **Numerical columns** — per-column histogram (with Freedman–Diaconis bin
  count), inline box plot, full statistics, and a distribution label derived
  from skew and kurtosis.
- **Categorical columns** — frequency table, horizontal bar chart, and a shape
  label (`constant`, `dominated by one category`, `high-cardinality /
  long-tail`, `roughly balanced`, `concentrated in few categories`).
- **Relationships** — correlation heatmap, scatter matrix, the ranked
  relationship table, and an interactive X/Y/colour scatter builder.
- **Auto-generated charts** — the selection engine output.

`bivariate_analysis()` samples down to 50,000 rows for speed and then looks for
three relationship families:

| Pair | Metric | Reported when |
|---|---|---|
| numeric × numeric | Pearson \|r\| | top 10 pairs |
| numeric × categorical | Eta (√ of variance explained) | ≥ 0.50 |
| categorical × categorical | Cramér's V (χ² based) | ≥ 0.40 |

`EDAResult.strong_relationships` filters on `|metric| ≥ 0.6`, which is what the
chart engine and the insights module consume.

### Stage 6 — Insights

`generate_insights()` writes analyst-style sentences from five generators:

- `structural_insights` — shape, type mix, duplicate warning, missingness
- `distribution_insights` — skew beyond 0.5 / 1.5, coefficient of variation
  above 2, dominated and constant categoricals
- `relationship_insights` — one line per strong relationship, in plain English
  ("strong positive linear relationship… this may indicate redundancy")
- `quality_insights` — columns >10% missing, type anomalies, outlier
  concentrations, inconsistent labels, validation failures
- `time_insights` — date span and data density for every datetime column

Each `Insight` carries a `category` (`structure` / `distribution` /
`relationship` / `anomaly` / `data_issue`) and a `severity` (`info` /
`warning` / `error`). The report sorts errors first, and the tab shows an
overall health bar plus an expanded "top issues" section.

### Stage 7 — Score

See [§5](#5-scoring-model). The tab renders a Plotly gauge (colour-graded by
letter band), a radar chart overlaying *before* and *after* cleaning, a
dimension breakdown table with per-dimension improvement, and a plain dict of
deltas.

### Stage 8 — Report

`build_report_data()` gathers every stage's output into one `ReportData`
dataclass, and the two renderers share a single section builder so the HTML and
PDF say exactly the same things:

1. Dataset overview (file, shape, timestamp, score)
2. Column profile table
3. Data quality (completeness, duplicates, outliers, type issues, validation)
4. Cleaning actions (only when cleaning ran)
5. Automated insights
5b. Key bivariate relationships
6. Score breakdown with per-dimension detail text

Three downloads are offered: the HTML report (styled, print-ready), the PDF
report (reportlab, landscape A4, repeating table headers), and the cleaned
dataset as CSV. If reportlab is missing the PDF button degrades to a warning
and HTML remains available.

---

## 5. Scoring model

The overall score is a weighted mean of five dimensions (`score.py:23`):

| Dimension | Weight | How it is derived |
|---|---:|---|
| **Completeness** | 0.25 | Banded on the filled-cell percentage — a flat penalty scale (≥99% → 0, ≥95% → 5, ≥90% → 12, ≥75% → 25, below → 50) rather than a linear rate, so a handful of empty cells is not scored as harshly as half an empty column |
| **Consistency** | 0.20 | Penalties for mis-typed cells (capped at 30 per column) plus inconsistent categorical labels (5 + 6 per affected column, capped at 35) |
| **Validity** | 0.20 | Weighted violation share, with `error`-severity failures counting 1.5×; −40 points per full unit of violation share, floored at 0 |
| **Uniqueness** | 0.15 | `100 × (1 − duplicate share)`, with a further penalty when duplicates exceed 5% of rows |
| **Accuracy** | 0.20 | Share of numeric cells that are not IQR outliers, penalised up to 60 points |

Grade bands: **Excellent** ≥ 90 · **Good** ≥ 80 · **Fair** ≥ 65 · **Poor** ≥ 50 ·
**Critical** below. `score_delta_after_cleaning(before, after)` returns the
per-dimension difference, which is what makes the improvement table possible.

---

## 6. Architecture

```
.
├── app.py           Streamlit dashboard — session state, tabs, widgets   (835 lines)
├── config.py        Shared constants and UI label maps                   (34)
├── load.py          Ingestion: encoding/delimiter sniffing, chunking     (245)
├── profile.py       Profiling + column-type detection                    (225)
├── quality.py       Six-part quality inspection suite                   (435)
├── clean.py         Configurable cleaning pipeline + audit log           (361)
├── eda.py           Numeric / categorical / bivariate / multivariate EDA(279)
├── visualize.py     Plotly chart builders + auto-selection engine       (307)
├── insights.py      Natural-language insight generation                 (229)
├── score.py         Five-dimension quality scoring                      (161)
├── report.py        ReportData + HTML/PDF renderers                     (316)
├── requirements.txt
└── tests/
    └── test_pipeline.py   27 end-to-end smoke checks                    (199)
```

### Module contracts

| Module | Public entry points | Return type |
|---|---|---|
| `load` | `load_dataset`, `detect_encoding`, `detect_delimiter` | `LoadResult` |
| `profile` | `detect_column_types`, `profile_dataset`, `infer_dtypes_from_types`, `unique_counts` | `dict[str, ColumnTypeResult]`, `ProfileResult` |
| `quality` | `run_quality_analysis`, `missing_report`, `duplicate_report`, `type_consistency_checks`, `detect_outliers`, `analyze_categorical`, `run_validation`, `validate_logical`, `missingness_heatmap`, `plot_outliers` | mixed dataclass/dict bundle |
| `clean` | `run_cleaning`, `impute_missing`, `drop_duplicates`, `correct_dtypes`, `standardise_categories`, `handle_outliers` | `(DataFrame, CleaningLog, list)` |
| `eda` | `run_eda`, `numeric_analysis`, `categorical_analysis`, `bivariate_analysis`, `compute_correlation`, `cramers_v` | `EDAResult` |
| `visualize` | `histogram`, `boxplot`, `grouped_box`, `bar_chart`, `pie_chart`, `donut_boolean`, `time_series`, `scatter`, `corr_heatmap`, `scatter_matrix`, `stacked_bar`, `auto_generate_charts` | `go.Figure` / `list[dict]` |
| `insights` | `generate_insights`, `summarize_top_issues` | `InsightReport` |
| `score` | `compute_quality_score`, `score_delta_after_cleaning`, `grade_for` | `QualityScore` |
| `report` | `build_report_data`, `generate_html_report`, `generate_pdf_report` | `ReportData` / `str` / `bytes` |

### Data flow

```
file ──▶ load_dataset ──▶ LoadResult.df
                              │
                              ├─▶ detect_column_types ──▶ {col: ColumnTypeResult}
                              │        │
                              │        ├──▶ profile_dataset ──▶ ProfileResult
                              │        ├──▶ run_quality_analysis ──▶ quality bundle
                              │        ├──▶ run_cleaning ──▶ cleaned df + CleaningLog
                              │        │        │
                              │        │        └──▶ re-detect types ──▶ quality + score (after)
                              │        ├──▶ run_eda ──▶ EDAResult ──▶ auto_generate_charts
                              │        ├──▶ compute_quality_score ──▶ QualityScore
                              │        ├──▶ generate_insights ──▶ InsightReport
                              │        └──▶ build_report_data ──▶ ReportData ──▶ HTML / PDF
                              │
                              └──▶ session state (memoised per stage)
```

`ColumnTypeResult` is the keystone: quality, cleaning, EDA, charts, insights and
scoring all read the *same* detection result, so every stage agrees on what a
column is. It carries its own evidence, which is why the Profile tab can show
*why* a column was classified the way it was.

### Chart selection engine

`auto_generate_charts(df, column_types, eda, n_charts=8)` ranks candidate
charts and returns `{"title", "fig", "reason"}` dicts — the reason string is
displayed in the UI, so every auto-chosen chart explains its own presence:

1. Histogram of the **most skewed** numeric column (skew sorts it to the front)
2. Scatter matrix, when there are ≥2 numeric columns
3. Box-plot comparison of numeric columns
4. Bar chart of the *most interesting* categorical (`_pick_interesting_cat`
   scores 2–12 unique values highest, free text lowest)
5. Pie chart of a second low-cardinality categorical (≤20 unique)
6. Donut for the first boolean column
7. Time series for the first datetime column, paired with the first numeric
8. Correlation heatmap
9. The strongest detected relationship, charted appropriately — scatter for
   num–num, grouped box for num–cat, stacked bar for cat–cat

---

## 7. Programmatic (headless) usage

Every stage is importable and free of Streamlit dependencies, so the same code
can run in a script, a notebook or a scheduler:

```python
import pandas as pd
from load import load_dataset
from profile import detect_column_types, profile_dataset
from quality import run_quality_analysis
from clean import run_cleaning
from eda import run_eda
from insights import generate_insights
from score import compute_quality_score
from report import build_report_data, generate_html_report, generate_pdf_report

result = load_dataset("data.csv")           # accepts a path or any file-like object
df = result.df
print(f"encoding={result.encoding} delimiter={result.delimiter!r} truncated={result.truncated}")

types = detect_column_types(df)
profile = profile_dataset(df, types)
quality = run_quality_analysis(df, types)

cleaned, log, stats = run_cleaning(
    df, types,
    imputation={"age": "median"},
    drop_dups=True,
    standardise_cats=True,
    outlier_action="cap",
)

cleaned_types = detect_column_types(cleaned)
cleaned_quality = run_quality_analysis(cleaned, cleaned_types)
eda = run_eda(cleaned, cleaned_types)
insights = generate_insights(cleaned, profile, cleaned_quality, eda)

score = compute_quality_score(
    cleaned,
    cleaned_quality["missing"],
    cleaned_quality["duplicates"]["count"],
    cleaned_types,
    cleaned_quality["type_issues"],
    cleaned_quality["categorical"],
    cleaned_quality["validation"],
    cleaned_quality["outliers"],
)

report = build_report_data(
    file_name="data.csv", df=cleaned, profile_result=profile,
    quality_result=cleaned_quality, outlier_summary=pd.DataFrame(),
    insight_report=insights, quality_score=score, cleaning_log=log, eda_result=eda,
    is_cleaned=True,
)
open("report.html", "w", encoding="utf-8").write(generate_html_report(report))
open("report.pdf", "wb").write(generate_pdf_report(report))
```

Inspecting a single column type without the full pipeline:

```python
>>> detect_column_types(df)["age"]
ColumnTypeResult(column='age', kind='numerical', confidence=0.75)
```

---

## 8. Bundled sample datasets

The Upload tab generates three datasets on demand with a fixed RNG seed
(`np.random.default_rng(42)`), so the demo is identical on every run. None are
bundled as files — they are built in memory, which keeps the repository small
and means the numbers quoted in the docs are reproducible.

| Sample | Shape | Contents | Deliberate problems |
|---|---|---|---|
| **Numeric-heavy** | 5,000 × 7 | sales, profit_margin, units_sold (Poisson), days_to_ship, return_rate, customer_age, order_value (exponential) | heavy right tails, plenty of IQR outliers, low missingness |
| **Categorical-heavy** | 4,000 × 6 | region, customer_segment, product, channel, repeat_customer, tier | messy casing (`north` / `NORTH`), trailing whitespace (`south `), near-duplicate labels (`Gadget C` / `Gadget c`) |
| **Mixed dataset** | 1,500 × 8 | transaction_id, date (daily), amount, category, city, email, age, is_fraud | 21 non-numeric `age` values, 10 malformed emails, 10 missing amounts, 10 missing dates, 4% fraud base rate |

The categorical-heavy sample is the one to use when demonstrating fuzzy label
merging; the mixed sample when demonstrating type correction and validation.

---

## 9. Configuration reference

All shared constants live in `config.py`:

| Constant | Value | Meaning |
|---|---|---|
| `APP_NAME` / `APP_VERSION` | — / `1.0.0` | Shown in the sidebar, page title and report header |
| `MAX_ROWS` | `200_000` | Hard cap on analysed rows; the sidebar warns when a file was truncated |
| `CHUNK_SIZE` | `50_000` | Rows per lazy CSV read |
| `OUTLIER_IQR_DEFAULT` | `1.5` | IQR multiplier (also the function default) |
| `OUTLIER_Z_MIN_ROWS` | `8` | Row floor for statistical outlier tests |
| `VALID_EMAIL_PATTERN` | regex | `^[^@\s]+@[^@\s]+\.[^@\s]+$` |
| `VALID_TEL_PATTERN` | regex | `^\+?\d[\d\s().-]{6,}$` |
| `PLOTLY_TEMPLATE` | `plotly_white` | Applied to every figure |
| `CATEGORY_MAX_UNIQUE_DISPLAY` | `15` | Cardinality threshold in type detection |
| `SKEW_THRESHOLD` | `1.0` | Reference skew level for labels |
| `OUTPUT_DIR` | `./outputs` | Reserved location for generated artefacts |
| `CLEANING_METHODS_LABELS` | dict | UI strings for the 7 imputation methods |
| `OUTLIER_ACTIONS_LABELS` | dict | UI strings for flag / cap / remove |

---

## 10. Testing

`tests/test_pipeline.py` is a self-contained smoke suite — no pytest, no
fixtures, no network. It generates its own datasets and runs every module
against all three data shapes, exiting non-zero on any failure.

```bash
$ python tests/test_pipeline.py
=== Pipeline: numeric-heavy ===
  [PASS] load            [PASS] profile         [PASS] quality
  [PASS] cleaning        [PASS] eda+visualize   [PASS] insights
  [PASS] score           [PASS] report
  [PASS] eda+visualize_scatter_dirty_numeric
...
PASSED: 27  FAILED: 0
```

**Current status: 27 / 27 passing.**

What each stage's check asserts:

| Check | Assertion |
|---|---|
| `load` | result frame is non-empty in both dimensions |
| `profile` | one type per column, and the type counts sum to the column count |
| `quality` | every key of the bundle has the expected type; both Plotly quality figures build |
| `cleaning` | at least a start+end log entry, output rows ≤ input rows, result is a DataFrame |
| `eda+visualize` | numeric/categorical lists are lists, auto chart selection returns a list, heatmap builds |
| `eda+visualize_scatter_dirty_numeric` | a column with 20% junk still classifies as `numerical`, and `scatter()` plus the whole auto-chart path survive it |
| `insights` | at least one insight, all with non-empty text |
| `score` | `0 ≤ overall ≤ 100`, dimension keys match `DIMENSION_WEIGHTS` |
| `report` | HTML > 1 KB; PDF > 1 KB, starts with `%PDF` and ends with `%%EOF` |

The dirty-numeric regression check is the important one: it pins the behaviour
where a column detected as numerical contains unparseable strings, which is
exactly the case the bundled *Mixed dataset* produces.

---

## 11. Work completed

**Ingestion layer**
- Multi-format loader (CSV/TSV/TXT/XLSX/XLS/JSON) with extension dispatch and a
  CSV fallback for unknown extensions
- Encoding detection with a validation-based fallback ladder rather than
  trusting chardet's guess blindly
- Delimiter sniffing against four candidates
- Chunked reading with early break at the row cap, and truncation reporting
- `_BytesLikeReadable` — a small file-like wrapper so in-memory bytes can be
  re-read by pandas' Python CSV engine (`readline` support was required)
- Support for paths, `UploadedFile` objects and any `.read()` file-like

**Semantic layer**
- Seven-rule column-type classifier with confidence scores and plain-English
  reasons, shared by every downstream module
- Profiling with deep memory measurement and a unified summary-statistics table
  covering numerics, categoricals, datetimes and booleans

**Quality engine**
- Six-part inspection suite: missingness (with heatmap), duplicates, type
  consistency, dual-method outlier detection, categorical analysis, and
  rule-based validation
- Rare-category and inconsistent-label detection via whitespace/case
  normalisation
- Self-derived value-range validation (1st–99th percentile widened by 10 IQRs)
  so no schema is required
- Cross-column `start`/`end` and `from`/`to` logical checks
- Graceful degradation on all-NaN, single-row, and constant-variance columns

**Cleaning engine**
- Configurable pipeline covering seven imputation strategies, duplicate
  removal with subset support, dtype coercion, fuzzy label standardisation, and
  three outlier strategies
- `CleaningLog` / `CleaningAction` audit trail with timestamps, affected-row
  counts, and a `to_dataframe()` view for the UI and CSV export
- Greedy fuzzy clustering over length-sorted labels so the shortest spelling
  wins as canonical
- `rapidfuzz` treated as optional — the module degrades gracefully
- Read-only preview coercion helper that never touches the loaded frame

**EDA engine**
- Distribution classification from skew and kurtosis
- Freedman–Diaconis bin selection
- Categorical shape classification with dominant-share and cardinality
- Three-family relationship discovery: Pearson, Eta, Cramér's V (via
  `scipy.stats.chi2_contingency`)
- Strong-relationship ranking and plain-language strength descriptors
- Row sampling for large frames to keep the UI responsive

**Presentation layer**
- 12 Plotly chart builders including an OLS trendline scatter, a 2-row
  histogram+box subplot, and a correlation heatmap with in-cell labels
- Automatic chart-selection engine with a written reason for every chart
- Gauge + radar score visualisations with grade-driven colour bands and
  before/after overlay

**Insight layer**
- Five insight generators covering structure, distribution, relationships,
  quality issues and time coverage
- Severity-sorted output with a convenience `summarize_top_issues()` helper

**Report layer**
- Single shared section builder feeding both renderers, so HTML and PDF cannot
  drift apart
- Styled, self-contained HTML with a print stylesheet
- reportlab PDF in landscape A4 with repeating table headers and zebra rows
- Minimal HTML-to-text de-corer for the PDF path, avoiding a weasyprint
  dependency that is painful to ship on Windows
- Cleaned-dataset and cleaning-log CSV exports

**App layer**
- Eight-tab dashboard with sidebar navigation, live pipeline progress, and
  per-stage session-state memoisation
- Upload de-duplication guard keyed on `(name, size)` so Streamlit reruns do
  not re-parse the file
- Full reset that re-runs the pipeline from the original upload
- Zero-data guard on every tab with a pointer back to Upload
- PDF export failure degrades to a warning instead of crashing the tab

**Verification**
- 27-case smoke suite covering all modules across three dataset shapes,
  currently all passing

---

## 12. Design decisions

**Typed dataclasses as contracts.** Every stage returns a frozen-ish dataclass
rather than a loose dict of arrays. `ColumnTypeResult`, `OutlierResult`,
`ValidationResult`, `CleaningLog` and `QualityScore` mean the UI, the report
generator and any headless script all consume the same shapes.

**One detection, shared everywhere.** Types are detected once at upload and
threaded through. Re-detecting per stage would let the profile call a column
categorical while the cleaner treated it as text.

**Evidence attached to every judgement.** Type detection records its reasons,
the chart engine records why each chart was chosen, the score records a detail
string per dimension. The app is meant to be argued with.

**Raw data is never mutated.** Cleaning returns a new frame; the raw upload
stays available for before/after comparison and for the score delta.

**Banded completeness rather than linear.** Completeness uses a penalty ladder,
so 99.9% completeness is not scored the same as 90% — the difference between
"almost clean" and "substantially missing" should show up in the score.

**Cap on expensive pair searches.** Cramér's V pair enumeration, scatter colour
groups, and box charts are all bounded, and EDA samples to 50,000 rows, so
wide datasets degrade in breadth rather than hanging the app.

**Graceful optional dependencies.** `rapidfuzz` and `reportlab` are imported
behind `try/except` with feature flags; the app runs without them, just with
fewer capabilities.

---

## 13. Known limitations

- **Row cap is 200,000.** Larger files are sampled from the top of the file for
  CSV, so results are a prefix rather than a random sample.
- **Excel reads are single-sheet** (the first sheet) and not chunked, so a very
  large workbook loads fully before truncation.
- **Cramér's V needs SciPy**, which is not listed in `requirements.txt` — it
  arrives transitively through `statsmodels`. Worth adding explicitly.
- **No persistence.** Session state is per-browser-session; reloading the page
  clears the analysis and there is no saved-project feature.
- **Cleaning is not undoable step-by-step.** The log is a record, not a
  reversible stack — undo means re-running with different settings.
- **`html_to_pdf_bytes()` is unimplemented** and raises `NotImplementedError`;
  `generate_pdf_report()` is the supported path.
- **Validation rules are heuristic.** The implied-range check will flag
  legitimately extreme values in heavy-tailed columns.
- **Charts are static images in the PDF.** The HTML report has no embedded
  Plotly figures either, so the reports are text and tables only.
- **Insights are rule-based**, not model-generated — they can only say what the
  implemented rules know how to say.
- **The `dataviz` skill is not applied**; chart styling is hand-rolled in
  `visualize.py` and could follow a stricter palette/accessibility spec.

---

## 14. Future work

- Persist analyses to disk so a session can be resumed
- Add a proper config/rule layer so users can declare their own validation
  constraints instead of relying on inferred ranges
- Undo/redo stack over cleaning steps
- Embed chart images into the PDF via Kaleido
- Upload multiple files and compare quality scores side by side
- A CLI entry point (`python -m eda_tools data.csv --report out/`) wrapping the
  headless API
- Column-level data-contract export (JSON Schema / Great Expectations style)
- Unit tests per module alongside the smoke suite, and CI

---

## Requirements

```
streamlit>=1.32.0     pandas>=2.0.0      numpy>=1.24.0     openpyxl>=3.1.0
plotly>=5.18.0       scikit-learn>=1.3.0 chardet>=5.2.0    rapidfuzz>=3.5.0
reportlab>=4.0.0     matplotlib>=3.8.0  seaborn>=0.13.0   statsmodels>=0.14.0
```

`statsmodels` is what makes Plotly's `trendline="ols"` on the scatter chart
work, and it is also where SciPy (needed directly by `cramers_v`) comes from.
`scikit-learn`, `matplotlib` and `seaborn` are not imported by any module —
Plotly covers all rendering — and can be dropped from the install if you want it
leaner.
