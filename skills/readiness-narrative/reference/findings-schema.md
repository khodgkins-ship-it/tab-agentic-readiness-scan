# `findings.json` — field guide

`findings.json` is the scan's single source of truth. Everything you write must
trace to a field here. Top-level keys are exactly:

```
meta   facets   domains   flags   coverage   findings
```

There is **no** top-level `score` or `maturity` key, by design — do not invent
one.

Internal identifiers (a facet's `id` like `semantic.singularity`, a flag's `id`
like `SEM-02`) are **join keys, not reader-facing labels**. Always render the
human name from the mapping tables at the bottom of this file. The rendered HTML
and markdown reports already show names — you can also read them there.

> **Never print a code in anything the client sees** — not in a heading, a table,
> or in parentheses beside a name. The mapping tables at the bottom of this file
> exist so *you* can look a code up and write its name. A code like `SEM-02` or
> `adoption.reach` means nothing to a client.

---

## `meta` — run header

| Field | Meaning |
|---|---|
| `run_id` | Unique id for this scan run, e.g. `run_20260914T214810`. |
| `site_name` | The Tableau site scanned. |
| `build` | `"working"` (full detail) or `"presentation"` (redacted — no formulas/owner names). |
| `framing` | `"full"` or `"light"`. **May be absent → treat as full.** If `"light"`, emit no stage/score/ladder language. |
| `deployment_type` | `"cloud"` or `"server"`. |
| `scan_started_at` / `scan_completed_at` | Scan window (ISO 8601). |
| `generated_at` | When the report was emitted. |
| `tool_version`, `query_set_version`, `app_template_version` | Provenance/versioning. |
| `core_metrics` | The metrics the assessment scoped to (e.g. `revenue`, `active_customer`). |
| `grouping_mode` | `"local"` or `"model_assisted"`. If model-assisted, metric grouping used a model pass — mention it for transparency. |
| `adoption_source` | Where adoption data came from (e.g. `fixture`, Admin Insights, repository). |
| `profile` | Optional named run profile (may be `null`). |

This is a **single point-in-time snapshot.** Do not describe a trend or
trajectory unless the client supplies a second run to compare against.

---

## `domains[]` — the spine of the narrative

One entry per decision domain. This is where readiness lives.

| Field | Meaning |
|---|---|
| `id` | Domain identifier, e.g. `revenue_ops`. |
| `target_stage` | The stage this domain intends to reach (1–6), set per domain. |
| `readiness` | Current stage, gated (the lowest gating dimension) — **not** an average. May be `null` (unscored). |
| `gap` | `target_stage − readiness`. |
| `binding_constraints` | List of facet codes that hold this domain back. **Name these** as the story. |
| `dimension_scores` | Per-dimension scores that produced the readiness, e.g. `{"governance": 1, "semantic": 2}`. |
| `unscored_dimensions` | Dimensions not measured for this domain — **coverage caveat, not a clean bill.** |
| `confidence` | `"observed"`, `"reported"`, etc. — how the readiness was established. |

**Empty `binding_constraints` handling:** if `binding_constraints` is `[]` but
`readiness < target_stage`, the constraint is still real — read
`dimension_scores` and name the lowest-scoring dimension as the effective
constraint, and note the `confidence`. Never write "no binding constraint" when
readiness is capped below target.

---

## `facets[]` — scored sub-lenses

The measured sub-lenses that roll up into dimensions.

| Field | Meaning |
|---|---|
| `id` | Dotted facet code (join key), e.g. `adoption.reach`. Render the name. |
| `dimension` | Parent dimension code, e.g. `adoption`. Render the name. |
| `score` | 1–6, or `null` when unmeasured (coverage gap — not a zero). |
| `evidence` | Evidence level, e.g. `"observed"`. |
| `confidence` | Confidence in the score. |
| `gates` | Which stage entry/entries this facet gates, e.g. `[3]`. |
| `derivation` | Human string explaining the score, e.g. `"band 4: measure 0.85 satisfies '> 0.7'"`. |
| `inputs` | The raw measures behind it, e.g. `{"content_activation": 0.85}`. |

---

## `flags[]` — specific issues found

| Field | Meaning |
|---|---|
| `id` | Catalog code, e.g. `SEM-02`, `SEC-01`. Render the name. |
| `severity` | e.g. `"informational"`, `"warning"`, `"critical"`. |
| `confidence` | Confidence the flag is real. |
| `facet` | The facet it attaches to (join key). |
| `domain` | The affected domain, or `""` if estate-wide. |
| `count` | How many objects tripped it. |
| `evidence` | A dict of supporting figures (varies by flag). |

---

## `coverage[]` — what was and wasn't measured

| Field | Meaning |
|---|---|
| `measure` | The thing that was attempted, e.g. `custom_sql`, `data_quality_warnings`. |
| `status` | `"ok"` = measured. Anything else (`"skipped"`, etc.) = a gap. |
| `reason` | Why it was skipped/degraded. |

**Every row whose `status` is not `"ok"` is a caveat you must surface.** An
unmeasured area must never read as a healthy one.

---

## `findings` — the detailed findings blocks

A subset of these keys is present depending on what the scan measured:

- **`definition_multiplicity`** — how many core metric concepts have competing
  definitions. Fields include `multiplicity_group_count`, `contested_group_count`,
  `usage_measured`, and `groups[]` (each with `variant_count`,
  `workbooks_affected`, `disagreeing_variants`, dominance state). When
  `usage_measured` is `false`, `null`, or absent, you **cannot** say which variant
  "wins" or is dominant — say so, and report the concrete counts instead
  (`variant_count`, `disagreeing_variants`, `workbooks_affected`).
- **`security_exposure`** — calculated fields enforcing access in the view layer
  (`user_context_field_count`, `affected_workbook_count`, and affected workbooks).
- **`retirement`** — unused-capacity case (`workbooks_total`,
  `zero_view_workbooks`, view-concentration figures, redundant source tables).
  Respect `usage_measured`: when `false`, `null`, or absent, a zero-view figure
  means *not measured*, not *unused* — present idle-workbook counts as
  candidates, not a settled tally. The redundant-source-table and
  view-concentration figures do not depend on usage and can be reported directly.
- **`governance_posture`** — observed presence of governance mechanisms, by arc
  (preventive/detective/corrective/accountability/assurance), with good/bad
  examples. This is **evidence, not a rating** — it never becomes a score.

Redacted values (presentation build) appear as `"[redacted]"`. Never reconstruct
them.

---

## Stage number → name

| Stage | Name | Verb |
|---|---|---|
| 1 | Minimal | Find |
| 2 | Emerging | Ask |
| 3 | Performing | Understand |
| 4 | Optimizing | Recommend |
| 5 | Leading | Act |
| 6 | Autonomous | Operate |

## Dimension code → name

| Code | Name |
|---|---|
| `data` | Data |
| `semantic` | Semantic |
| `action_surface` | Action surface |
| `governance` | Governance |
| `operating_model` | Operating model |
| `adoption` | Adoption |
| `value` | Value |

## Facet code → name

| Code | Name |
|---|---|
| `semantic.singularity` | Metric singularity |
| `semantic.describability` | Metric describability |
| `semantic.exposure_shape` | Data-source exposure shape |
| `semantic.consensus` | Definition consensus |
| `semantic.lifecycle` | Semantic lifecycle |
| `adoption.reach` | Adoption reach |
| `adoption.decision_culture` | Decision culture |
| `data.entitlement_at_source` | Entitlement at source |
| `data.provenance` | Data provenance |
| `data.freshness` | Data freshness |
| `data.retained_grain` | Retained grain |
| `data.integrity` | Data-integrity signals |
| `action.reversibility` | Action reversibility |
| `operating.ownership` | Operating ownership |
| `value.attribution` | Value attribution |
| `governance.accountability` | Ownership accountability |
| `governance.assurance` | Certification assurance |
| `governance.preventive` | Preventive controls |
| `governance.detective` | Detective controls |
| `governance.corrective` | Corrective controls |

## Flag code → name

| Code | Name |
|---|---|
| `SEC-01` | Access rule buried in a formula |
| `SEC-02` | Overly broad permission |
| `SEM-01` | Many variants of one metric |
| `SEM-02` | No agreed metric definition |
| `SEM-03` | Undocumented fields |
| `SEM-04` | Oversized data source |
| `SEM-05` | Inconsistent field descriptions |
| `DF-01` | Reliance on embedded extracts |
| `DF-02` | Redundant upstream tables |
| `DF-03` | Chained published sources |
| `DF-04` | Source without a traceable origin |
| `DF-05` | Stale data still in use |
| `DF-06` | High refresh-failure rate |
| `DF-07` | Grain loss in custom SQL |
| `DF-08` | Divergent source columns |
| `GOV-01` | Data source without an owner |
| `GOV-02` | No data-quality monitoring |
| `GOV-03` | Certified but flagged content |
| `EST-01` | Unused workbooks |
| `EST-02` | Many business-rule editors |
| `ADO-01` | Shallow user adoption |
| `ADO-02` | Concentrated viewership |

If you meet a code not in these tables, humanize it readably (replace `.`/`_`
with spaces) rather than showing the raw code — and treat its absence as a gap in
this guide, not a code to expose.
