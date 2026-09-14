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

_TBD at M3._
