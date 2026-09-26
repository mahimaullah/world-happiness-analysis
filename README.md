# What Actually Drives National Happiness?

An end-to-end analysis of the **World Happiness Report 2024**, built as a full ETL pipeline
(extract → clean → engineer features → load to SQLite) behind a source-to-target reconciliation
layer, followed by three analytical findings that test how well economics alone explains national
wellbeing.

**Stack:** Python · pandas · NumPy · SQLite / SQLAlchemy · Matplotlib · Jupyter

---

## The question

The Happiness Report decomposes each country's score into six contributing factors. The obvious
story is "richer countries are happier." This project tests where that story holds — and, more
interestingly, where it breaks.

## Pipeline

| Stage | What happens |
|---|---|
| **Extract** | Pulls the 2024 dataset (143 countries × 11 columns) via the `kagglehub` API |
| **Transform** | Normalizes column names, drops incomplete records (143 → 140 countries, each exclusion logged by name), coerces 7 numeric fields, engineers 3 new analytical columns |
| **Load** | Writes the cleaned frame to a SQLite database (`project.db`, table `happiness`) |
| **Reconcile** | Proves the load: 27 source-to-target checks, all passing (see below) |
| **Analyze** | Correlation analysis, linear residual modeling, and a controlled group comparison — each reproducible in pandas *and* re-queryable in SQL |

**Engineered features:** `happiness_tier` (Low / Medium / High bands), `gdp_quartile` (enables
within-wealth comparison), and `non_gdp_score` (the portion of a country's score not attributable
to GDP).

## Source-to-target reconciliation

"143 in, 140 out" is a count, not a reconciliation. It tells you three records are gone, not
whether they were excluded on purpose or lost. The reconciliation layer closes that gap.

**27 checks, 27 passed**, across row counts, key uniqueness, referential integrity, control totals
and round-trip verification:

- **Rows tie:** `143 source = 140 loaded + 3 rejected`.
- **Control totals tie:** seven column totals match source to target to 3 decimal places
  (e.g. `Ladder_score` sums to 774.325 on both sides).
- **Round trip:** the loaded table is read back out of SQLite and compared against the frame that
  was written.

Every dropped record goes to a variance log under a named reject rule. All three exclusions —
**Bahrain, Tajikistan and State of Palestine** — fall under `RJ-03`: a valid ladder score but no
factor decomposition, so they can't take part in any factor-level analysis. The 3-record variance
is a documented exclusion, not silent data loss.

`src/reconciliation.py` is dataset-agnostic and returns a non-zero exit code on failure, so it can
run as a gate in a scheduled job. All findings below reproduce unchanged with the reconciliation
layer in place.

## Findings

**1. The strongest driver changes depending on how happy a country already is.**
Globally, social support correlates most strongly with the happiness score (r = 0.81), followed by
GDP (r = 0.77) and healthy life expectancy (r = 0.76). But that ranking does not hold within tiers:
among Low-happiness countries GDP's correlation collapses to r = 0.09 while social support stays at
r = 0.38 — evidence that income explains very little at the bottom of the index. Corruption
perception behaves in the opposite direction, mattering most in the High tier (r = 0.65) and
essentially not at all in the Low tier (r = 0.11).

**2. Eight countries beat their GDP-predicted happiness by a full point or more.**
Fitting happiness against GDP alone and ranking the residuals surfaces Venezuela, Mozambique,
Nicaragua, Finland, El Salvador, Kosovo, Honduras and Costa Rica as the largest over-performers.
Seven of the eight score above the global average on freedom, and five score above average on
social support, led by Finland (+0.44) and Costa Rica (+0.24) — the surplus is consistently social
and institutional, not economic.

**3. Among wealthy countries, corruption is worth ~0.66 happiness points.**
Holding income roughly constant by filtering to the top two GDP quartiles (n = 70) and splitting at
the median corruption score, low-corruption nations average **6.65** vs **5.98** for their
high-corruption peers. The low-corruption group also scores higher on freedom (0.72 vs 0.63),
suggesting transparent governance travels with stronger civic institutions rather than acting alone.

## Reproducing this

```bash
pip install -r requirements.txt
jupyter lab world_happiness_analysis.ipynb   # Kernel ▸ Restart & Run All
python src/reconciliation.py                 # exits non-zero if any check fails
```

The notebook downloads its own data and runs top-to-bottom on a fresh kernel with no manual steps.

## Limitations

The 2024 report omits roughly 50 nations, many in active conflict or without the statistical
infrastructure to run the survey, which biases global averages upward and makes the Low tier the
least reliable segment. Scores are also **self-reported life satisfaction**, not an external
assessment of a country's governance or conduct — a state can score well while acting in ways
widely condemned internationally, so the index should not be read as a measure of national virtue.
Finding 2's residuals come from a single-variable linear fit, which is deliberately simple: it is a
device for surfacing outliers, not a predictive model. Natural next step would be joining external
indicators (press freedom, Gini coefficient, conflict intensity) to find where reported wellbeing
diverges from conditions on the ground.

---

*Original analysis built for Data Curation & Management, Rutgers University. Reconciliation layer
added September 2026.*
