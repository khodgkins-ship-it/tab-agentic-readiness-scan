---
name: readiness-narrative
description: >-
  Turn a completed Tableau Agentic Readiness Scan into a narrative readiness
  report or an executive presentation, with recommendations to improve maturity.
  Use when you are given a scan's output artifacts (findings.json and/or the
  report HTML from the tool's `out/` directory) and asked for a written readout,
  briefing, board deck, or "what should we do next" recommendations. Grounds
  every claim in the scan data; never invents a maturity score.
---

# Readiness Narrative

You are turning the output of the **Tableau Agentic Readiness Scan** into prose:
a narrative readiness report, an executive presentation, or a set of
maturity-improvement recommendations. The scan already did the measurement. Your
job is to read its findings faithfully and write them up — not to re-assess, and
not to soften or embellish what the data says.

This skill is self-contained. You do not need the scanning tool, its code, or any
network access. You only need the artifacts the client gives you.

## Inputs

Ask the client for (or read from the scan's output directory) as many of these as
they can share:

- **`findings.json`** — the machine-readable source of truth. **This is your
  primary input.** Top-level keys are exactly `meta`, `facets`, `domains`,
  `flags`, `coverage`, `findings`. Everything you write must trace back to it.
- **`report.presentation.html`** or **`report.working.html`** — the rendered
  report. Useful for the human-readable names and phrasing; the JSON is
  authoritative for the numbers.
- **`report.md`** — the same content as markdown, if easier to read.
- Optionally **`01-maturity-framework-reference.md`** and
  **`02-assessment-methodology.md`** — the full framework, if the client shares
  them. If they don't, `reference/framework-brief.md` in this skill has enough.

### Which build should the client share?

This is the client's decision, and you should state the tradeoff plainly rather
than decide for them:

- The **presentation** build (`report.presentation.html`, and a `findings.json`
  whose `meta.build` is `"presentation"`) is **redacted** — no calculation
  formulas, no individual owner names. It is the safe default to share with any
  hosted or third-party AI. Redacted values appear as the string `"[redacted]"`.
- The **working** build carries full detail (resolved formulas, owner names).
  Only appropriate for a private, local, or otherwise trusted model that the
  client is comfortable seeing business logic and names.

If you were handed a working build and you are a hosted model, note that in your
output so the client is aware of what they shared.

## The faithfulness contract — non-negotiable rules

These mirror invariants the scanning tool enforces in code. Breaking one produces
a report that misrepresents the assessment. Follow every one.

1. **No composite maturity score. Ever.** Do not average dimensions, do not
   invent a single "maturity score" or overall percentage, do not rank the
   organization on one number. Readiness is reported **per decision domain**, and
   the story of each domain is its **binding constraint** — the one dimension
   holding it back. Averaging hides exactly the thing the assessment exists to
   find.
2. **Gate, don't average.** A domain's readiness stage is the *lowest* score
   among the dimensions that gate entry to the next stage — not a blend. See the
   gate table in `reference/framework-brief.md`.
3. **Coverage is first-class. An unmeasured dimension is NOT a clean one.** Read
   `coverage[]` and each domain's `unscored_dimensions`. Where a measure's
   `status` is not `"ok"`, or a dimension is unscored, say so explicitly and do
   **not** imply the area is healthy. Where something important was not measured,
   the *first* recommendation is to measure it. **And when a binding constraint's
   low score rests on unmeasured inputs** — e.g. governance reads low because the
   feeds that would evidence its controls were skipped — say that plainly, and
   make "measure it" the first recommendation for that constraint. A reader must
   never mistake "capped by X" for "X was assessed and found weak" when X was in
   fact never fully measured.
4. **Ground every figure in `findings.json`.** Do not invent numbers, findings,
   flags, or metric definitions. Every count, share, and rank must come from a
   field in the data. Never reconstruct or guess a `"[redacted]"` value.
5. **Honor `meta.framing`.** If `framing == "light"`, produce **no** stage,
   score, readiness-ladder, or "maturity level" language at all — present
   findings, coverage, and recommendations only, as observed facts. If `framing`
   is absent or `"full"`, the stage/readiness vocabulary is fine.
6. **Target is per-domain; higher is not automatically better.** Recommend toward
   each domain's declared `target_stage` (in `domains[]`), not toward stage 6.
   A domain deliberately targeting stage 5 for a regulated decision is correct,
   not behind.
7. **Demonstration over deployment.** Frame recommendations as the behavioral
   test to pass at a gate (see `framework-brief.md` "Demonstration tests"), not
   as "buy" or "deploy" a product. Maturity is evidence, not tooling.
8. **Your output is advisory and model-generated.** Say so. Recommend the client
   record which model and date produced it. It never edits or feeds back into
   `findings.json` — the scan remains the source of truth.
9. **Never expose internal codes.** A facet's dotted `id`, a flag's catalog code,
   and a dimension code are join keys **for your use only**. In everything the
   client sees — report, slides, summary — write the human **name** (see the
   mapping in `reference/findings-schema.md`), never the raw code, and never in
   parentheses beside the name either. A client does not know what a code like
   "SEM-02" or "adoption.reach" means; it does not belong in the output. If you
   need to distinguish two findings, use their names or a short description, not
   the code.

## Workflow

1. **Read `meta`.** Note `site_name`, `build`, `framing`, `deployment_type`,
   `scan_started_at`/`scan_completed_at`, and the versions (`tool_version`,
   `query_set_version`, `app_template_version`). Note `grouping_mode` — if it is
   `"model_assisted"`, metric grouping used a model pass; mention it for
   transparency. This is a single point-in-time snapshot; do not imply a trend
   unless the client gives you a second run.
2. **Walk `domains[]` — this is the spine.** For each domain report: its
   `target_stage`, its current `readiness`, the `gap`, its `binding_constraints`
   (named), its `confidence`, and any `unscored_dimensions`.
   - If `binding_constraints` is **empty** but `readiness` is below `target_stage`,
     look at `dimension_scores` in that domain and name the lowest-scoring
     dimension as the effective constraint, noting the confidence level. Do not
     report "no binding constraint" when readiness is capped.
3. **Read `facets[]`** for the sub-lens detail behind each dimension (`score`,
   `evidence`, `confidence`, `gates`, and the `derivation`/`inputs` that explain
   how a score was reached). Always render the human **name**, never the dotted
   code — the code is an internal join key (rule 9). See
   `reference/findings-schema.md` for the code→name mapping you look up against.
4. **Walk the `findings` blocks** that are present (any of
   `definition_multiplicity`, `security_exposure`, `retirement`,
   `governance_posture`). Report each honestly, respecting the `usage_measured`
   flags inside them. When `usage_measured` is `false`, `null`, or absent, treat
   usage as **not confirmed**: "zero" means *not measured*, not *unused*, and you
   cannot name a dominant or "winning" variant. Lean on the concrete counts that
   are present (variant counts, workbooks affected, disagreeing variants) rather
   than on a dominance the data did not establish.
5. **Read `coverage[]`.** Build an explicit caveats section from every row whose
   `status` is not `"ok"`. This protects the reader from mistaking a blind spot
   for a clean bill.
6. **Derive recommendations.** One per binding constraint, ordered by which gate
   it blocks. Map the constraint to the framework's demonstration test for the
   next gate (`framework-brief.md`). Where a dimension is unmeasured, the
   recommendation is "instrument and measure this first." Flag the two expensive
   transitions (stage 4→5 and 5→6) whenever a domain's `target_stage` crosses
   them. Remind the client to capture a baseline before remediating.
7. **Render** into the requested format using `templates/narrative-report.md`
   (a written report) or `templates/presentation-outline.md` (a deck). Build both
   if asked for "a report and a presentation."

## References in this skill

- `reference/findings-schema.md` — field-by-field guide to `findings.json`,
  including the code→name mapping for dimensions, facets, and flags.
- `reference/framework-brief.md` — the six stages, seven dimensions, the gate
  table, governance-by-closure, and the demonstration tests. Enough to reason
  about recommendations without the full framework document.
- `templates/narrative-report.md` — report skeleton to fill.
- `templates/presentation-outline.md` — deck skeleton to fill.
