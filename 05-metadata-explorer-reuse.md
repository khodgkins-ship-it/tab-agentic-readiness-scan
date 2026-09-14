# Reusing tableau-metadata-explorer

## Assessment and Reuse Plan

What `tableau/tableau-metadata-explorer` provides, what it does not, and how the estate scan relates to it.

```
https://github.com/tableau/tableau-metadata-explorer
```

This assessment was written from the repository's README, project summary, and user guide rather than from its source. Treat it as a hypothesis to verify against the code. Section 9 lists the specific things to confirm.

---

## 1. Verdict

Reuse its API client layer. Do not extend its application layer. Build the assessment pipeline as a separate deterministic module.

The repo is an interactive metadata exploration tool. A person asks a question in plain English, an LLM plans REST and GraphQL calls, a critic reviews the plan, a validator checks the syntax, and results render in a table. It does that well and it has solved problems we would otherwise have spent weeks on.

The estate scan is a different kind of software. Batch, unattended, deterministic, durable, and scored. The two overlap in their plumbing and diverge in everything above it.

**The architectural reason to keep them separate.** Their queries are LLM-generated per invocation. For assessment that is disqualifying. Findings have to be comparable across reruns on one account and across accounts, and a customer will eventually ask why a number moved between two scans. The answer cannot be that the model planned a different query. Assessment queries must be fixed, version-controlled, and reviewed, with the query version recorded in the run metadata.

Their AI layer still earns its place, after the scan. Once the deterministic pass has produced findings, natural language exploration of the same estate is genuinely useful for a specialist chasing a specific thread. Sequence it as scan first, explore second.

---

## 2. What the repo already provides

Substantial, and worth cataloguing so we do not rebuild it.

| Capability | Where | Notes |
|---|---|---|
| PAT sign-in for both APIs, session expiry handling | `tableau_rest.py` | Returns a session-expired signal rather than a raw 401. Exactly the behavior our spec asked for |
| REST client with pagination | `tableau_rest.py` | Including the POST-for-read pattern some endpoints require |
| GraphQL execution | `tableau_metadata.py` | Plus comment and query stripping |
| GraphQL schema grounding | `app/static/schema/*.md` | Types, filters, and a query library from live introspection. This is reference material we would have had to assemble ourselves |
| Query validation against schema | `query_validator.py` | Catches six real classes of error including totalCount placement, unused variables, and filters that do not exist |
| Multi-step orchestration with cross-step references | `orchestrator.py` | Output templating and filter construction from prior step results |
| Pagination cost estimation | `router.py` `_build_estimate` | Estimates total fetch time from totalCount and offers a safe-pages cap. Partially addresses our scale problem |
| Site size modeling | API Guide Modeler | Pulls real counts to estimate query cost before a large sweep |
| Deployment packaging | Docker, compose, Mac app, multi-user mode | Solves distribution for a field team |

**Hard-won API knowledge encoded in the repo.** Several constraints in their documentation would have cost us discovery time. Owner filtering does not exist on `workbooksConnection` and must route through REST. `totalCount` is a sibling of `pageInfo`. Nested connections take `first` only, with no pagination. GraphQL cannot filter on null or empty, so description-coverage work has to fetch and filter client-side. Bulk label retrieval returns 405. Treat their schema files as the reference for our fixed queries.

**Governance analyses that overlap our flags.**

| Their analysis | Our flag | Fit |
|---|---|---|
| Stale Content | EST-01 | Close. Theirs ranks by view count, which is better than a raw count |
| Description Coverage, with quality scoring | SEM-03 | Better than specced. They score description quality rather than only presence |
| Data Overlap, clustering workbooks by shared upstream tables | DF-02 | Close to fan-out, framed as redundancy |
| Duplicate Calculated Fields, semantically equivalent across data sources | SEM-01 | Partial, and the direction is inverted. See section 4 |
| Certification Readiness, scoring uncertified sources 0 to 5 | GOV adjacent | Useful, and a model for our threshold approach |
| Unused Fields | Not specced | Worth adopting. Feeds the retirement case |
| Dependency Map, projects to databases | Domain scoping | Useful input to the domain mapping problem |
| Catalog Health, REST against Metadata API divergence | Not specced | New finding. See section 5 |

---

## 3. Gaps against the estate scan requirements

Ordered by impact on the assessment.

| Gap | Severity | Why it matters |
|---|---|---|
| No persistent store | Blocking | Session-based. No run identity, no rerun comparison, no coverage record, no durable artifact. An assessment needs a database, not a table view |
| No deterministic query set | Blocking | LLM-planned queries cannot produce defensible comparable findings |
| No formula resolution | Blocking | Nested calculations are not comparable until resolved to base columns. Duplicate detection over unresolved formulas misses most real conflicts |
| No concept grouping | Blocking | Their duplicate detection solves the inverse problem. See section 4 |
| No usage-weighted variant ranking | High | The dominance measure is what sizes adjudication work and sorts the backlog |
| No security scan for user-context functions | High | Our highest signal-to-effort flag and a trivial addition. Formula contains USERNAME, ISMEMBEROF, FULLNAME, USERDOMAIN |
| No refresh or freshness analysis | High | No job history extraction, so no failure rate and no stale-source-feeding-active-workbook flag |
| No permissions extraction | High | No All Users grants, no locked permission coverage, no project permission model |
| No adoption or penetration data | High | KPI cards count metadata objects. No Admin Insights, so no penetration, concentration, or trajectory |
| No flag engine | High | No severity, confidence, thresholds in a tunable rules file, or suppression record |
| No facet scoring or domain scoping | High | Nothing connects findings to the maturity framework |
| No report generation | High | TSV export only. No customer report, no variant workbook |
| No unattended batch mode | High | Tier one is a free scan that runs without a human after launch |
| No material disagreement testing | Medium | Needs query execution through VizQL Data Service. Full mode only |
| No grain or aggregation detection | Medium | No custom SQL GROUP BY analysis, no extract row count comparison |
| Partial-response handling unclear | Medium | They validate syntax and estimate cost. No explicit node-limit partial-data detection was found in the documentation, which is our most dangerous failure mode. Verify in code before relying on it |
| Cloud only | Medium | Server support unstated. Our install base needs both |
| Metadata sent to an external LLM | Medium | Their AI analyses transmit customer metadata to Anthropic or OpenAI. The build spec requires local-first handling. See section 6 |
| No redaction or retention policy | Medium | Formulas are customer business logic |

---

## 4. The inverted duplicate problem

This is the most important technical finding from the review, and it is easy to miss.

Their Duplicate Calculated Fields analysis finds **the same logic in different places**. Two data sources each containing an equivalent revenue calculation, which is redundancy.

Our flagship finding is **the same concept with different logic**. Forty-seven calculations all named some variant of revenue, computing materially different numbers, which is ambiguity.

These are opposite operations over the same data. Deduplication groups by formula and reports distinct locations. Variant detection groups by concept and reports distinct formulas. One produces a cleanup list. The other produces an adjudication backlog.

Both are worth having and only one exists. The variant pipeline is new work.

```
Their direction:   formula hash → [locations]        → redundancy
Our direction:     concept       → [formula hashes]  → ambiguity
```

Reuse what transfers. Their semantic equivalence scoring is useful inside our normalization step, since two formulas differing only in field alias should collapse to one variant. But the grouping key is different, the resolution step is missing, and the usage weighting does not exist.

---

## 5. A finding the repo taught us

Their Catalog Health analysis compares descriptions between the REST API, treated as source of truth, and the Metadata API, treated as a cache, then finds labels and certifications present in one and absent from the other.

That is a flag we did not have and it matters more now than it did for them. A knowledge graph built over Metadata API content inherits whatever divergence exists between the cache and reality. Stale labels and out-of-sync descriptions become stale grounding.

**Add two flags to the rules file.**

`SEM-05`, warning. Description divergence between REST and Metadata API above a threshold share of scoped fields. Confidence observed. Facet semantic describability.

`GOV-03`, warning. Certifications or data quality warnings present in the Metadata API and absent in REST, or the reverse. Confidence observed. Facet governance detective.

Both are cheap, both are estate-specific, and both speak directly to grounding quality.

---

## 6. Data handling divergence

Their AI analyses send metadata, including calculated field formulas, to an external model provider. That is a reasonable choice for a self-service exploration tool a customer runs on their own site with their own key.

It is the wrong default for a field-run assessment, where a Tableau employee or partner operates the tool against customer metadata. The build spec calls for local-first with no exfiltration, and I would hold that line for the deterministic pass.

**Resolution.** The deterministic scan runs entirely local and emits counts, hashes, and structural measures. Concept grouping is the one step wanting model assistance, so make it explicitly opt-in, per run, with the customer informed, and support a fully local fallback using name and token matching at lower confidence. Record which mode ran in the run metadata, since it affects the confidence attached to every variant group.

---

## 7. Specification for the assessment layer

Build as a separate package. Import their clients. Do not modify their application.

```
assessment/
  clients/          ← thin wrappers over tableau_rest, tableau_metadata
  queries/          ← fixed, versioned GraphQL and REST query definitions
  extract/          ← sharded, resumable, raw-response caching
  store/            ← SQLite schema and loaders
  derive/           ← formula resolution, normalization, grouping, ranking
  flags/            ← rules file plus evaluation engine
  score/            ← facet scoring, domain rollup, binding constraint
  report/           ← findings.json, report.md, variants.xlsx, run.log
  cli.py            ← scan and full modes, unattended
```

### 7.1 Modules to build

**`queries/`.** Every query the assessment runs, as a versioned file with a checksum. Built from their schema reference so the constraints they documented are honored. The run records the query set version. No query is generated at runtime.

**`extract/`.** Their client handles a single call. This handles the campaign. Shard by project, then object type, then cursor. Persist shard state for resume. Cache raw responses before parsing. Add explicit partial-response detection, meaning check for an errors array and node-limit indicators on every response and subdivide the shard rather than accepting truncated data. Verify whether their client already surfaces this before implementing, and add it to their client as an upstream contribution if not.

**`store/`.** The SQLite schema from the build spec, including the coverage table. Every attempted measure records success or the reason it could not run.

**`derive/`.** All new. Recursive formula resolution with cycle and depth handling, scoped to the containing data source. Normalization that deliberately preserves filter conditions, date boundaries, and aggregation choices. Concept grouping in three passes with confidence recorded. Usage-weighted ranking and dominance.

**`flags/`.** Declarative rules file, tunable without code change, with severity, confidence, thresholds, and suppression. Includes the two new flags from section 5.

**`score/`.** Facet scores, domain rollup by minimum over gating facets, governance by loop closure, binding constraint per domain. No composite score.

**`report/`.** Four artifacts. The variant workbook is the one the field actually uses in adjudication sessions.

### 7.2 What to extract that they do not

New extraction beyond their coverage. REST job and task history for refresh analysis. REST permissions, project level for all and content level sampled. Admin Insights through VizQL Data Service for adoption. Custom SQL text with GROUP BY detection. Extract row counts where available for grain inference.

### 7.3 Reuse notes

Their `query_validator.py` should run over our fixed query set in CI rather than at runtime. A schema change that breaks a query then fails the build instead of silently degrading a customer scan. That is a better use of the validator than the one it was written for.

Their Modeler approach to site-size cost estimation should inform our shard sizing defaults.

---

## 8. Contribution strategy

Three pieces belong upstream rather than in our fork, because they improve the shared tool and reduce our maintenance burden.

Partial-response detection in the GraphQL client, if absent. This is a correctness bug affecting every consumer, not a feature.

Server support in the client layer, if we build it.

The user-context function scan, since it is a governance analysis any admin would want and it fits their dashboard naturally.

Keep in our layer everything tied to the maturity framework, meaning facet scoring, domain rollup, flag severity, and the customer report. Those encode a point of view and a commercial motion rather than general-purpose metadata analysis.

---

## 9. What to verify in code before building

This assessment is based on the README, project summary, and user guide. Five things need confirming against the source, and each changes scope.

Whether the GraphQL client detects node-limit partial responses or accepts truncated data.

Whether the REST client covers jobs, tasks, and permissions endpoints or only content endpoints.

Whether any usage or view data comes from Admin Insights or only from REST content usage stats, since Stale Content ranks by view count and the source matters.

Whether Server is supported anywhere in the client layer or whether Cloud assumptions are baked in.

What the Duplicate Calculated Fields analysis does with nested calculations, since that determines how much of the resolution work is genuinely new.
