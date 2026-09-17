# Decisions Log — Tableau Estate Scan

Living record of the decisions and milestones behind this build. Two sections:
**Remaining** (open decisions and work still to do) and **Completed** (decisions
already made and milestones already landed). The forward plan lives in
`~/.claude/plans/wiggly-mixing-noodle.md`; this log tracks what has actually been
decided and shipped against it.

_Last updated: 2026-09-17._

---

## 1. Remaining — decisions and milestones to continue later

The planned milestones **R0–R6 are all committed** (see §2). What remains is not
new milestone work; it is (a) work deferred by design, (b) cleanup created by two
later scope reversals, and (c) committing the current in-flight changes.

### Deferred by design

- **Live credentials & guarded live smoke.** The live path is interface-complete
  and offline-tested, but has never run against a real site ("interface-complete
  now, credentials later"). When a read-only PAT exists: run the guarded
  live-smoke path (R6) against a real Cloud *and* Server, confirming sign-in,
  extraction, partial-response subdivision, and sign-out. Never in CI.
  - The PAT must be supplied by the user in their own terminal via
    `ESTATE_SCAN_PAT_SECRET` / `ESTATE_SCAN_PAT_NAME` or the OS keychain — never
    stored in config, never handled inside this tooling's automation.
  - A real PAT was once pasted in plaintext during development; it should be
    **rotated** if that has not already happened.
- **Threshold calibration from real engagements.** Thresholds remain provisional
  and must not be tuned against the synthetic fixtures. The calibration harness
  (R6) emits the real distributions; set thresholds from live data later.

### Cleanup created by later scope reversals

- **Multi-run / cross-run comparison — decide whether to retire it.** R5 built
  `estate_scan/report/compare.py` (`compare_runs`, `render_comparison_markdown`).
  A later decision ruled the tool **single-snapshot only** (point-in-time
  assessment, not change tracking). Open decision: remove/retire that module and
  any surfacing of it, or leave it dormant. Do **not** invest further in
  cross-run features. (See memory: scope-no-cross-run-no-corrective.)
- **R6 upstream contributions — likely moot.** R6 committed upstream contribution
  notes (`44aef13`), prepared but unopened. The user has since handled the
  tableau-metadata-explorer feedback manually and wants the contribution work
  dropped. Open decision: remove/archive those notes. Do not open upstream PRs.
  (See memory: no-upstream-contributions.)

### Housekeeping

- **Commit the in-flight working set.** A large uncommitted changeset sits on top
  of the R6 commit — modifications across clients, extract, flags, queries,
  score, store, fixtures, and tests, plus new files (`report/labels.py`, and
  `queries/v1/data_quality_warnings.graphql`,
  `queries/v1/database_tables.graphql`). Review and commit (or split) this before
  starting anything new so the tree is clean.

### Standing constraints (not to be reopened without the user)

- **Corrective governance arc stays interview-only** — not extended into the
  observed-presence pattern. `governance_posture.arcs` stays `[preventive,
  detective]`. (See memory: scope-no-cross-run-no-corrective.)

---

## 2. Completed — decisions already made

### Governing decision

- **Build the real application the prototype demonstrates** — real connectivity
  to Tableau Cloud/Server, robust checks across all seven assessment dimensions,
  and fuller reporting. Additive on top of the prototype, not a rewrite.

### Locked scope decisions

- **Both Cloud and Server from day one** (not Cloud-first). One `LiveClient`, no
  subclass split; deployment differences are capability-gated.
- **Interface-complete now, real credentials later** — every live client fully
  built and CI-green against mocked transports before any live site exists.
- **Include VDS (VizQL Data Service) read-only queries** for resolving material
  disagreement between metric variants.
- **Build framing-light report mode now** — the maturity-ladder-free rendering,
  selectable per account.

### Architecture / dependency decisions

- **Vendor the two upstream client modules** into `estate_scan/clients/` rather
  than depending on the repo as a package (keeps the build self-contained;
  sidesteps the Python-version mismatch).
- **`keyring` is an optional dependency, not a default** — env-var credential
  resolution is the stdlib floor and covers CI; keychain support degrades
  cleanly when `keyring` is absent. Default dependency footprint unchanged.

### Security posture (all enforced in code, each with a test)

- **Read-only against Tableau, enforced structurally** — three defense-in-depth
  gates: GraphQL by-name + operation check (Gate A), REST verb/resource allowlist
  (Gate B), and a transport guard raising `ReadOnlyViolation` (Gate C).
- **Never store PAT/secrets in config** — env var or OS keychain only; a startup
  scan hard-aborts if a secret appears in config, never echoing the value.
- **Sign out at the end of every run** — `close()` posts signout and nulls the
  token, best-effort/idempotent, in a `finally`.
- **Two redaction builds** — presentation (no formula text, no owner names) and
  working (full detail); a pre-emit secret scan fails the build on a hit.
- **No composite maturity score, anywhere** — `findings.json` top-level keys stay
  `{meta, facets, domains, flags, coverage, findings}`; the web-app payload is a
  strict subset.
- **Coverage is first-class** — an unmeasured dimension never reads as clean.
- **Local-first / no exfiltration by default** — the tool talks only to the
  customer's own Tableau host; the deterministic pass makes no external calls.
- **Do not tune thresholds against synthetic fixtures.**

### Milestones landed (committed on `main`)

| Milestone | Commit | Summary |
|---|---|---|
| M1 | `419c78e` | Fixture generator, client interface, offline replay client |
| M2 | `90b7268` | SQLite store + resumable shard-based extractor with partial-response detection |
| M3 | `19fba01` | Recursive formula resolution and normalization |
| M4 | `ea66628` | Concept grouping and usage-ranked dominance |
| M5 | `08350c2` | Declarative flag engine |
| M6 | `840043b` | Facet scoring, interview capture, four-subcommand CLI |
| M7 | `1ba9809` | Report emit — five artifacts, two redaction builds, offline web app |
| R0 | `e3d6a11` | Verify upstream against source, lock client contract, gate the query set |
| R1 | `2e60cb6` | Live clients (Cloud+Server), read-only enforced in code, offline-tested |
| R2 | `3086c77` | Extract coverage for the four deferred dimensions |
| R3 | `39f3c4e` | VDS read-query executor and material-disagreement resolution |
| R4 | `909bf49` | Full dimension + flag coverage, governance binding-constraint fix |
| R5 | `3fe8bae` | Fuller reporting — framing-light, VDS surfacing, multi-run comparison* |
| R6 | `f4d4f7b`, `9a0b09d`, `44aef13` | Guarded live-smoke path, calibration harness, upstream contribution notes* |

\* R5's multi-run comparison and R6's upstream contribution notes were built, then
superseded by later scope decisions (see §1, "Cleanup created by later scope
reversals").

### Later scope decisions (post-milestone)

- **Tool is single-snapshot only** — no cross-run/multi-run comparison focus.
  Narrows R5; treat multi-run as dropped, not pending.
- **Corrective governance arc stays interview-only** — not extended into the
  observed-presence evidence pattern (correction is a state transition a single
  scan can only infer from residue, which risks overclaiming).
- **No upstream contributions** — the tableau-metadata-explorer feedback was
  handled manually; the R6 contribution work is dropped.

### Work completed this session (uncommitted)

- **Internal codes replaced with human-readable names across all output assets.**
  Facet/flag/dimension codes (`SEM-03`, `DF-01`, `semantic.describability`,
  `action_surface`) never appear in consumer-visible output; the reader sees a
  name and description instead. New presentation catalog
  `estate_scan/report/labels.py` is the single source of truth, consumed by the
  markdown report and the web-app payload (codes remain only as internal join
  keys). Verified with two regression tests and a live render; full suite green
  (252 passing).

- **Concept grouping rewritten to exact formula-signature bucketing** (replaces
  transitive union-find). The old design linked fields that shared a single base
  column *or* a single name token and stitched the links with union-find. On a
  templated estate that chains catastrophically: a date-spine column like
  `[Current Year]` and boilerplate name tokens (`value`, `total`, `perf`, `vs`,
  `mtd`) each appear in thousands of unrelated fields, so one shared item fused
  thousands of distinct KPIs into a single spurious "concept" (the reported
  failure: "Cost per CM member" grouping four unrelated calculations). Frequency
  cannot separate a real metric noun from boilerplate, so the distinction is
  semantic, not structural.
  - **New algorithm.** Each candidate field joins exactly **one** bucket keyed by
    its canonical formula signature — `(agg-function set, base-column set,
    is-ratio)`. Exact-key bucketing (O(n), no threshold, no transitive linking),
    so a shared column or token can never chain distinct concepts. Confidence
    tiers: a bucket whose members share one normalized hash is `exact_match` /
    high; a bucket spanning several hashes is `formula_signature` / medium. Tier
    2 (model-assisted semantic merge) stays **opt-in, OFF by default** — a
    recorded no-op — per precision-first.
  - **Decision: precision-first, accept under-grouping.** Differently-*shaped*
    definitions of one business metric (Net Rev = SUM([Sales]) − SUM([Discount])
    vs Revenue = SUM([Sales])) land in **separate** groups; merging them is a
    semantic judgment reserved for the opt-in model pass. The tool never
    fabricates a merge (upholds "the tool never authors a definition").
  - **Decision: keep per-group counting; re-derive expectations, do not tune to
    fixtures.** SEM-01/SEM-02 fire per signature bucket, so definition sprawl is
    honestly **under-reported** (only a single-definition bucket that itself
    exceeds threshold trips SEM-01). The planted manifest ground truth was **not**
    corrupted to match degraded detection; tests assert the algorithm's honest
    output over the manifest with documenting comments.
  - **Downstream re-derivation.** On the median fixture the dominant-variant share
    rises to 0.583 (many small dominated buckets) → `semantic.singularity` scores
    **3** (was 2), clearing the stage-2 floor, so the target-5 `revenue_ops`
    domain now names `data.entitlement_at_source` as its **sole** binding
    constraint (was tied with singularity). Test expectations across
    `test_group.py`, `test_flags.py`, `test_report.py`, and `test_score.py`
    re-derived accordingly; a new `test_every_group_is_signature_coherent`
    invariant guards against regression.
  - **Verified on real estate data** (deterministic re-derive on a throwaway copy
    of the live DB, no credentials/network): 17,060 candidate fields → 3,589
    signature-coherent groups, largest bucket 343 identically-shaped members — no
    catastrophic chaining; all 3,589 groups pass the coherence invariant. Full
    suite green (261 passing).
