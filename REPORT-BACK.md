# Report-back notes (build brief §8)

Running notes toward the four things to report when M7 lands. Updated as each
milestone reveals something.

## 1. What the metadata explorer's GraphQL client does with partial responses

**Status: ported, source not yet verified against the live repo.**

The reuse plan (`05-metadata-explorer-reuse.md`) describes `tableau_metadata.py`
as exposing a `classify_result` that recognises node-limit partial responses.
This prototype runs offline and the `tableau/tableau-metadata-explorer` repo has
not been cloned into this sandbox, so the classification in
`estate_scan/clients/base.py::classify_graphql` was ported from the *documented*
behaviour, not read off the source. Specifically:

- HTTP 200 with a top-level `errors` array is normal, not fatal.
- An `errors` entry whose `extensions.code` is a known warning code
  (`NODE_LIMIT_EXCEEDED`, `TIME_LIMIT_EXCEEDED`, ...) **with** `data` present is
  a *partial* result: usable but known-incomplete.
- Any other error code, or null `data`, is fatal.

Acting on partial (subdividing the shard) is our extract layer's job
(`extract/runner.py`), never upstream's.

**To confirm before upstreaming:** clone the repo, read
`app/proxy/tableau_metadata.py`, and check whether `classify_result` (a) exists
under that name, (b) enumerates the same warning-code set, and (c) already
subdivides or merely classifies. If it only classifies (likely), subdivision is
a genuine upstream contribution candidate. **Do not open a PR without asking.**

## 2. Specified fields that could not be confirmed against the schema reference

- `datasource_fields.graphql`: field-type connections
  (`calculatedFieldsConnection`) appear to filter only on `id`/`name`/`isHidden`/
  `text`, **not** `datasourceId`, contradicting spec 02 §5 / 03 §5.1. Worked
  around by scoping through `publishedDatasourcesConnection(filter:{idWithin})`
  and paginating the nested `fieldsConnection`. **Needs live-schema
  confirmation.**
- `CalculatedField.referencedBySheets` (aliased `sheetsUsedIn`): modelled as a
  plain list per the spec §5.1 example. On a large estate this nested list may
  itself hit a node limit and need to become a paginated connection. **Unconfirmed.**
- `published_datasources.graphql`: `upstreamDatasources { id luid name }` for the
  published-on-published lineage (DF-03) is marked **UNCONFIRMED** in the query
  file.

## 3. Observed distribution of variant counts and dominance ratios (median fixture)

**Status: instrumented at M4.** `rank.py::rank_groups` returns
`variant_count_distribution`, `dominance_ratios`, and per-group `detail`. These
are the numbers a real engagement would set thresholds *from*; on synthetic data
they are reported, not acted on (build brief §7 — the dominance rule is not
tuned against fixtures).

Observed on `tests/fixtures/median` (5 concept groups, 82 grouping candidates,
22 entitlement fields excluded):

| group | variants | group_views | cover80 | dominant | top÷2nd ratio |
|---|---|---|---|---|---|
| revenue | 47 | 10000 | 3 | **yes** | 5.64 |
| active_customer | 14 | 12500 | 7 | no | 1.36 |
| gross_margin | 8 | 5200 | 6 | no | 1.11 |
| average_order_value | 7 | 4800 | 5 | no | 1.20 |
| churn_rate | 6 | 4000 | 5 | no | 1.25 |

Variant-count distribution: `{6:1, 7:1, 8:1, 14:1, 47:1}`.

**Do the provisional thresholds (share ≥0.60, ratio ≥2.0) look sane?** Against
this fixture, yes, but only because the fixture was built to separate cleanly:
the one intentionally-dominant group clears both gates by a wide margin (0.62
share, 5.64 ratio) and the four contested groups sit far below the ratio gate
(1.1–1.4). There is nothing in the 1.4–2.0 band, so the fixture cannot tell us
whether 2.0 is the right cut — it only confirms the rule fires on an obvious
case and stays silent on obviously-contested ones. **A real engagement is
needed to populate the ambiguous middle; do not read the clean separation here
as validation of the threshold value.**

**Confidence-method observation.** Every median group resolves as
`formula_token`/medium, never `exact_match`/high, because each concept is
multi-variant by construction, so no group is a single exact-normalized cluster.
The high-confidence path is real but only exercised on the `small` (clean)
fixture, where a metric with one definition should group at high confidence. The
`method_counts` summary makes this visible per run.

## 4. Where the resolution logic felt underspecified

Building M3 surfaced five decisions the spec's pseudocode leaves open. Each was
resolved conservatively (favouring "flag, don't guess / don't drop"); all are
worth a second opinion:

- **Multi-defect status precedence.** A field's subtree can contain more than
  one defect (e.g. a reference that is both deep and dangling). The spec lists
  four statuses but not which wins. Chosen precedence, worst-first:
  `cycle > too_deep > unresolved_reference > resolved`. A cycle is treated as
  the most fundamental because it makes the field non-computable at all.
- **`resolution_depth` meaning.** The spec's `depth` is a recursion counter used
  only for the cap; it does not say what to persist. Persisted value is the
  chain length with a leaf calculation counting as depth 1 (matching the fixture
  generator's ground-truth convention), so the two can be compared later.
- **Text carried by a non-resolved field.** The spec says never drop a field but
  not what `resolved_formula` should hold for a cycle / too-deep / unresolved
  field. Chosen: the best-effort partial expansion with the offending token left
  in place, so the row is inspectable and the status flags why it is incomplete.
- **Ambiguous references have no status of their own.** The spec says to build
  the token map from name *and* caption and to "flag ambiguous matches rather
  than guessing", but does not give ambiguity a `resolution_status`. Folded into
  `unresolved_reference` (the reference is left unexpanded) and counted
  separately in the resolver summary (`ambiguous_refs`). Captions are absent from
  the current fixtures, so this path is exercised only by construction, not by
  data — a live run is where it will first bite.
- **`field_refs` is untyped.** The schema does not distinguish a reference to a
  calculated field from one to a base column. Both are recorded, which makes the
  table a full reference graph; a consumer that only wants calc-to-calc edges
  must join against `fields.is_calculated`.

Related under-normalization decision (see §... / normalize.py): commutative
argument-list sorting is listed in the spec as a "where safe" option and is
deliberately not implemented, because judging safety in a flat token stream is
the kind of guess that manufactures false collapses.
