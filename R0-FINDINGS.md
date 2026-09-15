# R0 findings — upstream verified against source, contract locked, enforcement designed

The prototype (M1–M7) ran offline with the `tableau/tableau-metadata-explorer`
repo un-cloned, so several claims about upstream were carried from the README /
project summary / user guide rather than the source. R0 clones the repo and
answers the five verify questions in `05-metadata-explorer-reuse.md §9` (and
`06-build-brief.md §8`) **against the source**, records the vendor decision, and
notes where each answer changes scope for the real build.

Source read at R0: `tableau/tableau-metadata-explorer`, Apache-2.0,
Copyright (c) Salesforce, Inc. (shallow clone; primary files
`app/proxy/tableau_metadata.py`, `tableau_rest.py`, `admin_insights.py`,
`governance.py`, `router.py`, `host_validator.py`, `constants.py`,
`query_validator.py`).

---

## The five §9 questions

### (a) Does the GraphQL client detect node-limit partial responses, or accept truncated data?

**It detects them — but not everywhere, and reaction is inconsistent.**
`tableau_metadata.classify_result()` exists under that name and recognises the
node-/time-limit warning family: an HTTP 200 whose top-level `errors[]` carry a
known warning code (`NODE_LIMIT_EXCEEDED`, `TIME_LIMIT_EXCEEDED`, …) **with**
`data` present is a *partial* result (usable, known-incomplete); any other code
or null `data` is fatal. Our `estate_scan/clients/base.py::classify_graphql`
mirrors that rule and warning-code set exactly.

What the source also shows — and what the earlier "upstream only classifies"
note got imprecise in both directions:

- **Detection is not universal.** `classify_result` is one code path, not a gate
  every response passes through. `execute()` returns raw responses without
  classifying; the raw `/proxy/metadata` passthrough forwards a truncated 200
  as-is; and `duplicate_calculated_fields` (governance.py) calls `execute()` then
  treats *any* `result.get('errors')` — including the same warning codes — as a
  **hard failure**, not a usable-partial.
- **Reaction is inconsistent.** At least one caller *does* subdivide —
  `router.py`'s `fetch_more` halves the page size on a limit warning — while
  others do neither.

**Scope impact.** Our design makes both steps uniform: every response is
classified in one place (`classify_graphql`) and acting on partial (subdividing
the shard, retrying) is the extract layer's consistent job
(`extract/runner.py`), never a per-caller choice. That uniformity — detect at
the transport boundary, subdivide consistently — is a genuine upstream
contribution candidate (prepared as notes/patches only at R6; **no PR without
asking**).

### (b) Does the REST client cover jobs, tasks, and permissions, or only content?

**Only content.** `tableau_rest.py` is a thin generic wrapper — `signin`,
`signout`, `get_site_role`, `is_full_site_role`, and generic
`call` / `call_xml` / `call_xml_raw` / `paginate`. Its callers reach only content
resources: `datasources`, `workbooks`, `views`, `projects` (plus the app's own
`datasources/{id}/tags` write for its sync tags, which is exactly the kind of
mutation our read-only guard rejects). There is **no** coverage anywhere in
`app/proxy/*` of `jobs`, `tasks`, `permissions`, `schedules`, or
`extractRefreshes` endpoints.

**Scope impact.** Permissions (SEC-02, GOV) and refresh/job history → freshness
(DF-05/06) are net-new REST work for us — confirmed as R2 milestone items, not a
port. The generic `call`/`paginate` shape is reusable as a *pattern* (we build
our own guarded, GET-only registry), but there is no endpoint coverage to
inherit.

### (c) Does usage/view data come from Admin Insights, or only REST content stats?

**Admin Insights, via the VizQL Data Service — not REST content stats.**
`admin_insights.py` sources usage from the Admin Insights datasources
`TS Users`, `Site Content`, and `TS Events`, queried through `vds.py` (VDS).
These are **admin-only** (the datasources populate only for full-site admins)
and **Cloud-only** (they are a Tableau Cloud feature). Functions degrade
gracefully to `available: False` when the datasource is missing or VDS is off.

**Scope impact.** This confirms the reuse doc's worry that "Stale Content ranks
by view count and the source matters": the real per-user penetration and
staleness signal lives in Admin Insights over VDS, not in REST. It sets the
source for our adoption-depth work (ADO-01, R2 — populate `user_id`/`event_date`
from Admin Insights, set `adoption_source` accordingly) and reinforces the VDS
executor decision (R3). On **Server**, where Admin Insights does not exist, this
dimension must record as `unavailable`/repository-sourced, never silently clean.

### (d) Is Server supported, or are Cloud assumptions baked in?

**Not supported end-to-end; the Cloud assumptions are in the version and usage
layers, not the host layer.** Nuance the earlier flat "Cloud assumptions baked
in" missed:

- **API version is pinned.** `tableau_rest.py` hardcodes `API_VERSION = "3.28"`
  with **no** `/api/serverinfo` negotiation. Tableau Server sites commonly run
  older API versions, so a pinned 3.28 breaks against them.
- **Usage/governance is Cloud-only.** Admin Insights over VDS (see (c)) has no
  Server equivalent, and there is no repository-based fallback.
- **But the host layer already contemplates Server.** `host_validator.py`
  supports an allowlist for on-prem hostnames (e.g. `tableau.mycorp.com`) and an
  explicit on-box-Server-over-loopback path — so addressing a Server is not
  itself blocked.

**Scope impact.** For "Both Cloud + Server from day one" we add `/serverinfo`
version negotiation (R1), a Server-appropriate usage source with capability
gating (R2), and treat Metadata-API-disabled-on-Server as a hard-abort
capability (R1). Cloud vs Server stays a recorded attribute + capability gates,
**not** a subclass split.

### (e) What does Duplicate Calculated Fields do with nested calculations?

**It does not resolve them.** `governance.py::duplicate_calculated_fields`:

1. fetches `CalculatedField` nodes with `formula` + `upstreamColumns` (base
   physical columns via lineage);
2. **pre-groups by the upstream-column fingerprint** (a `frozenset` of
   `table.column`), deterministic, no expansion;
3. compares **formula text** within each pre-group — either an LLM equivalence
   pass (`claude_ai.assess_duplicate_formulas`) or the deterministic
   `assess_calc_field_groups` fast path, whose `normalize_formula` only strips
   whitespace, lowercases, and substitutes aggregation aliases.

A formula that references another calculated field is compared as the literal
token (e.g. `[Other Calc]`); it is **never expanded** into that field's
definition. There is no cycle/depth handling and no transitive resolution.

**Scope impact.** Our recursive formula resolution (M3 — transitive expansion of
calc-references, cycle and depth detection, `resolution_status`, normalized-hash
comparison) is **genuinely new work**, not a reimplementation of an existing
capability. This is the "inverted duplicate problem" of `05 §4`: upstream groups
by shared base columns then leans on text/LLM equivalence; we resolve
definitions deterministically first and group on the resolved hash.

---

## Vendor decision (reported per build brief §2)

**Decision: vendor only `query_validator.py` (+ its `types-and-filters.md`
whitelist source and a small `schema_loader` shim); build our own live clients.
Do NOT vendor the upstream client modules wholesale.**

The plan's default was "vendor the two upstream client modules
(`tableau_metadata.py`, `tableau_rest.py`) into `estate_scan/clients/`."
Reading the source changed that:

- The upstream client modules are **coupled to a Flask application** (tenant DB,
  settings, per-request logger) and to app concerns (host SSRF validation, an
  execution store) we do not want in a local-first CLI.
- They **pin API 3.28 with no `/serverinfo` negotiation**, are effectively
  **public-CA / Cloud-shaped**, and **lack** jobs/tasks/permissions coverage,
  Server version negotiation, and Cloud/Server capability handling — every one
  of which we must build regardless (see (b), (c), (d)).
- So there is little client *code* worth inheriting; the value is the **hard-won
  query-validation knowledge**, which is self-contained.

We therefore vendor `query_validator.py` (Apache-2.0, with the header block,
`LICENSE`, `NOTICE`, and marked modifications per §4b) and reuse the schema/VDS/
warning-code *knowledge* for our own `httpx`-based clients (R1). The validator
runs over our fixed query set as a build-time gate — see below.

`keyring` stays an **optional** dependency: env-var credential resolution
(`ESTATE_SCAN_PAT_SECRET` / `ESTATE_SCAN_PAT_NAME`) is the stdlib floor and
covers CI; `keyring` is imported behind `try/except` for the OS-keychain path
and degrades cleanly when absent. No change to the default dependency footprint
(httpx / jinja2 / openpyxl / pyyaml / pytest).

---

## Contract + gate status at end of R0

- **`EstateClient` contract finalized for live use.** `run_config()` is now a
  first-class method on the ABC (base returns `{}`); the extract runner reads
  `run_config()` / `site_id` / `site_name` / `deployment_type` /
  `adoption_source` directly rather than duck-typing them. The transport shape
  stays `graphql(query_name, variables)` / `rest(resource, params)` — no
  raw-text, verb, URL, or body parameter — which is *why* read-only is
  enforceable in R1.
- **`base.py` classification comment corrected** to the verified reality above
  (was overstated as "already recognises … upstream only classifies").
- **`query_validator` wired into CI** over `queries/v1/*` via
  `tests/test_queries.py`: every manifest query must validate with zero errors,
  a planted-defect test proves the gate has teeth (it is not a silent no-op),
  and a checksum-drift test (`verify_all()`) guards the fixed set. A schema-
  breaking query edit now fails the suite instead of silently degrading a live
  scan.
- **`REPORT-BACK.md §1`** updated from "source not yet verified" to the verified
  findings.

Full offline suite: green.
