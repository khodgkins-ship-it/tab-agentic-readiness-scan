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

_TBD at M4/M5 — instrument the run to emit the distribution. Do not tune
thresholds against synthetic data (build brief §7)._

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
