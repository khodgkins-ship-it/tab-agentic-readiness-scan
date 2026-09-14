# Estate Scan Tooling

## Build Specification

Engineering spec for the tool producing the estate findings. The assessment methodology document covers what to measure and why. This covers how to build it.

Validate every API object, field, and endpoint against current documentation for both Cloud and Server before implementing. Names and availability differ between deployment types and change between releases. Treat the queries here as structure and intent rather than as verified syntax.

---

## 1. Design constraints

**Local-first, no exfiltration.** Calculated field formulas are customer business logic and occasionally contain embedded literals with sensitive values. Extraction, storage, and analysis all run on a machine the customer or the field team controls. Nothing uploads anywhere by default. Build a redaction pass and a retention policy before the tool goes to anyone outside the team, because a specialist running this on a customer laptop is the expected deployment.

**Resumable.** A full scan on a large estate runs for hours and will fail partway. Every extraction stage writes raw responses to disk before parsing, and the pipeline restarts from the last completed shard rather than the beginning.

**Read-only.** The tool never writes to a Tableau site. No exceptions, and enforce it in code rather than by convention.

**Two run modes.**

| Mode | Scope | Time | Needs |
|---|---|---|---|
| `--mode=scan` | Metadata API, REST API, Admin Insights. Produces the three GTM findings and all observable flags | Hours unattended | Admin credentials |
| `--mode=full` | Adds domain scoping input and material disagreement testing through query execution | Plus 2 days with a customer analyst | Query execution path and a domain map |

Tier one is the free scan offered in the field guide. It must run without a human in the loop after launch.

**Degrade rather than fail.** Missing Admin Insights, a disabled Metadata API, or absent job history each disable specific flags. The tool reports what it could not measure as a first-class output rather than silently omitting it. A report that quietly skipped freshness looks like a clean freshness finding.

---

## 2. Architecture

```
  extract/          →   store/           →   derive/          →   flag/         →   report/
  raw API responses     normalized SQLite    computed measures    rule engine      artifacts
  cached to disk        one row per object   variant clusters     severity+conf    md, xlsx, json
```

Five stages, each independently runnable against the previous stage's output. Keep them separate. The derivation and flag logic will change far more often than the extraction, and re-extracting a large estate to test a threshold change is unacceptable.

**Suggested stack.** Python, `httpx` with retry and backoff, SQLite via plain SQL rather than an ORM, `pandas` for derivation, Jinja for report rendering. Package as a CLI with a single config file.

---

## 3. Authentication

One sign-in, two APIs. The REST API sign-in returns a credentials token that the Metadata API also accepts as `X-Tableau-Auth`.

```
POST /api/{version}/auth/signin
  personalAccessTokenName, personalAccessTokenSecret, site contentUrl
  → token, site id, user id
```

**Operational notes.**

- PAT sessions expire and there is a concurrent session cap per token. Long scans need a refresh loop keyed to elapsed time rather than to a caught 401, since a 401 mid-shard wastes the shard.
- Sign out at the end of every run, including on failure, or you leak sessions against the cap.
- Store the PAT in an environment variable or OS keychain. Never in the config file, and add a startup check refusing to run if a secret appears in config.
- Server deployments may require the Metadata API to be enabled explicitly. Detect and report this rather than surfacing a confusing GraphQL error.

---

## 4. Deployment capability detection

Server carries a large share of the install base and Knowledge reaches it in H2 2026, so deployment differences need specifying rather than discovering.

### 4.1 Capability detection, not deployment branching

Do not branch on Cloud against Server. Probe capabilities at startup and record what is available, because a Server deployment with the Metadata API enabled and repository access behaves closer to Cloud than to a locked-down Server.

```
capabilities = {
  metadata_api:        graphql introspection succeeds
  rest_jobs:           /sites/{s}/jobs returns 200
  rest_tasks:          /sites/{s}/tasks/extractRefreshes returns 200
  admin_insights:      Admin Insights project and datasources present
  repository:          direct workgroup connection configured and reachable
  vizql_data_service:  endpoint responds
  data_quality_api:    dataQualityWarnings returns 200
}
```

Every capability writes to `coverage` with status and reason. Flags depending on an absent capability are `unmeasured`, never absent.

### 4.2 Server substitutes

| Measure | Cloud source | Server substitute | Confidence |
|---|---|---|---|
| Active users, penetration | Admin Insights | `historical_events` and `users` in the repository | Observed, lower |
| View counts per workbook | Admin Insights | `views_stats` or `historical_events` filtered to view actions | Observed, lower |
| Stale content | Admin Insights | Same repository path | Observed, lower |
| View concentration | Admin Insights | Same repository path | Observed, lower |
| Refresh history | REST jobs | `background_jobs` in the repository | Observed |
| Retention window | Roughly 90 days | Site-configured, often longer | Record actual |

Repository access needs a read-only workgroup user, which many customers will not grant on a first engagement. When it is unavailable, the adoption facets are `unmeasured` and the report says so. Do not infer adoption from content counts, since a large estate with no usage data is exactly the case where inference misleads.

Record `adoption_source` in run metadata as `admin_insights`, `repository`, or `unavailable`. It affects comparability across accounts and any later threshold calibration.

### 4.3 Other divergences to handle

The Metadata API may be disabled on Server, and this is the one capability without a substitute. Detect it, fail with a clear message naming the setting, and do not attempt the scan.

Metadata API indexing on Server can lag or be incomplete after an upgrade. Where an indexing state is exposed, record it. Where it is not, note in coverage that index freshness is unverified.

Repository schema differs across Server versions. Pin the queries to a stated version range, detect the version, and fail loudly on an unsupported one rather than returning wrong counts.

---

---

## 5. Extraction

### 5.1 Metadata API

Endpoint is the GraphQL path on the site. Use the `*Connection` forms with cursor pagination throughout, never the unbounded list forms, which time out on any real estate.

**The failure mode to design for.** GraphQL returns partial data alongside errors when node limits are exceeded. A naive client reads `data`, finds records, and reports success while silently missing most of the estate. Every response must be checked for an `errors` array and for node-limit indicators, and a partial response must trigger shard subdivision rather than acceptance. This is the single most likely way the tool produces a confidently wrong report.

**Sharding strategy.** Shard by project first, then by object type, then by cursor page. If a shard returns partial data, subdivide it and retry. Persist shard completion state so a restart resumes.

```graphql
query Workbooks($first: Int!, $after: String) {
  workbooksConnection(first: $first, after: $after) {
    nodes {
      id luid name projectName createdAt updatedAt
      owner { username }
      upstreamDatasources { id name }
      embeddedDatasources { id name }
      sheets { id name }
      dashboards { id name }
    }
    pageInfo { hasNextPage endCursor }
    totalCount
  }
}
```

Extract in this order, since later stages reference earlier identifiers.

1. Projects
2. Published data sources with upstream tables, upstream databases, and downstream workbooks
3. Workbooks with embedded data sources and sheets
4. Fields, split by type. Columns and calculated fields need different selection sets
5. Custom SQL tables with query text and downstream references
6. Database tables and columns

**Field extraction is the volume problem.** A thousand-workbook estate with heavy embedded usage produces tens or hundreds of thousands of field records, since every embedded data source carries its own copy. Shard field extraction by parent data source, not globally, and expect this stage to dominate runtime.

```graphql
query CalcFields($first: Int!, $after: String, $dsId: ID!) {
  calculatedFieldsConnection(first: $first, after: $after,
                             filter: {datasourceId: $dsId}) {
    nodes {
      id name formula description
      datasource { id name __typename }
      fields { id name }
      referencedByFields { id name }
      sheetsUsedIn: referencedBySheets { id name workbook { id luid } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
```

Capture `__typename` on the parent data source. Distinguishing published from embedded is central to several flags and easy to lose in normalization.

### 5.2 REST API

The Metadata API does not cover permissions, refresh operations, or job history. Everything below comes from REST.

| Need | Endpoint shape | Notes |
|---|---|---|
| Users, groups, membership | `/sites/{site}/users`, `/groups`, `/groups/{id}/users` | Paginated. Needed for domain scoping by owner |
| Content permissions | `/sites/{site}/workbooks/{id}/permissions`, same for datasources and projects | Per-object call, so this is the rate-limit hot spot |
| Project permission model | `/sites/{site}/projects` | Look for locked permissions and permissive defaults |
| Extract refresh tasks | `/sites/{site}/tasks/extractRefreshes` | Schedules |
| Job history | `/sites/{site}/jobs` | Success and failure over the retention window |
| Data quality warnings | `/sites/{site}/dataQualityWarnings/...` | Presence and coverage |

**Do not fetch permissions for every object.** On a four-thousand-workbook estate that is four thousand sequential calls and it will trip rate limits. Fetch project-level permissions for all projects, then sample content-level permissions for the active set plus anything in the target domains. Report the sampling basis in the output.

Implement a shared rate limiter with exponential backoff on 429 and a concurrency cap. Make both configurable, since limits differ by deployment.

### 5.3 Admin Insights and adoption

Cloud exposes Admin Insights as published data sources in a dedicated project. Query them through the VizQL Data Service rather than trying to download extracts.

```
POST /api/v1/vizql-data-service/query-datasource
  datasource: { datasourceLuid }
  query: { fields: [...], filters: [...] }
```

Pull view events by workbook and user over 90 days, user activity for penetration, and feature or capability usage where exposed.

**Server has no Admin Insights.** Substitute the repository through a read-only workgroup user, or Server Insights where present. The measures differ, so record which source produced the adoption numbers and mark the flags derived from them with lower confidence when using a substitute.

**Retention limits the trajectory finding.** Cloud Admin Insights typically holds 90 days, which is enough for stale-content and concentration measures and not enough for the four-quarter trajectory the field guide asks for. Get trajectory from account records rather than from the scan, and say so in the report.

### 5.4 Query execution, full mode only

Material disagreement testing needs actual results, not metadata. Two paths.

VizQL Data Service against the relevant published data source, which is preferable since it respects Tableau semantics and permissions.

Direct warehouse execution where the variants resolve to base tables, which is faster and risks diverging from what Tableau would compute.

Either way, run against a fixed recent period, log the exact executed logic, and record the connection identity used. Never run this without the customer analyst present and never in `--mode=scan`.

---

## 6. Local data model

SQLite. Normalized, one row per object, with a `run_id` on everything so multiple scans of the same site coexist and can be compared.

```sql
runs(run_id, site_id, deployment_type, started_at, completed_at,
     mode, tool_version, coverage_json)

projects(run_id, id, name, parent_id, locked_permissions)

datasources(run_id, id, luid, name, kind, project_id, owner,
            is_certified, certification_note, has_extract,
            field_count, upstream_table_count, created_at, updated_at)

workbooks(run_id, id, luid, name, project_id, owner,
          created_at, updated_at, sheet_count, embedded_ds_count)

fields(run_id, id, name, description, datasource_id, field_type,
       data_type, role, formula, is_calculated)

field_refs(run_id, field_id, referenced_field_id)
field_usage(run_id, field_id, sheet_id, workbook_id)

custom_sql(run_id, id, query, datasource_id, char_length,
           has_group_by, has_user_function)

lineage(run_id, downstream_type, downstream_id,
        upstream_type, upstream_id, depth)

permissions(run_id, object_type, object_id, grantee_type,
            grantee_id, capability, mode, sampled)

refresh_jobs(run_id, task_id, datasource_id, scheduled_at,
             completed_at, status)

usage_events(run_id, workbook_id, user_id, event_date, event_count)

-- derived
resolved_formulas(run_id, field_id, resolved_formula, normalized_hash,
                  resolution_depth, resolution_status)

metric_groups(run_id, group_id, canonical_label, confidence, method)
metric_variants(run_id, group_id, field_id, normalized_hash,
                usage_rank, view_count, workbook_count, is_dominant)

flags(run_id, flag_id, severity, confidence, facet, domain,
      evidence_json, count, created_at)

coverage(run_id, measure, status, reason)
```

The `coverage` table is not optional. Every measure the tool attempted records whether it succeeded, and the report renders it. This is how the tool avoids presenting an unmeasured dimension as a clean one.

---

## 7. Derivation

### 7.1 Formula resolution

A calculation referencing another calculation is not comparable until resolved to base columns.

```
resolve(field, depth=0, seen=set()):
    if field.id in seen: return CYCLE
    if depth > MAX_DEPTH (default 12): return TOO_DEEP
    formula = field.formula
    for each referenced calculated field r:
        formula = substitute(formula, r.token, "(" + resolve(r, depth+1, seen ∪ {field.id}) + ")")
    return formula
```

Record `resolution_status` as resolved, cycle, too deep, or unresolved reference. Never drop unresolved fields silently, and report the counts, since a high unresolved rate is itself a finding about estate complexity.

**Two real pitfalls.** Field references appear by name in brackets, and names collide across data sources, so resolution must be scoped to the containing data source. And formulas may reference a field's caption rather than its name, so build the token map from both and flag ambiguous matches rather than guessing.

### 7.2 Normalization

Applied to resolved formulas before hashing.

Strip comments and collapse whitespace. Lowercase function names and identifiers. Standardize bracket and quote forms. Normalize numeric literal formatting. Sort commutative argument lists where safe, which catches trivially reordered logic.

**Do not normalize away** filter conditions, date boundaries, or aggregation choices. Those differences are usually the substance of the disagreement, and normalizing them produces a false clean result. When in doubt, under-normalize, since a false variant is a cheap error and a missed conflict is an expensive one.

### 7.3 Concept grouping

Hashing finds identical logic. Grouping finds the same business metric under different names, meaning Revenue, Total Revenue, Net Rev, and Rev USD.

Three-pass approach.

Exact and normalized name match, deterministic and high confidence.

Token and fuzzy match with a conservative threshold, medium confidence, and always human-reviewable.

Assisted grouping over the candidate list, low confidence until confirmed, presented to the customer's business owner for sign-off.

Persist `method` and `confidence` per group. Never present an assisted group as fact in a customer report.

**The hard rule.** Grouping and documentation drafting are appropriate uses of AI here. Authoring the authoritative definition is not, and the tool must not emit a recommended definition. Generating a definition from ambiguous source logic encodes the ambiguity while looking authoritative.

### 7.4 Usage ranking and dominance

Join variants to view counts through field usage, sheets, and workbooks, then rank within each metric group.

Define dominance explicitly and make it configurable. Provisional rule: a variant is dominant when it carries at least 60 percent of views across the group and at least twice the second-ranked variant. Emit `variants_covering_80pct_views` per group, since that number rather than the raw variant count is what sizes the adjudication work.

Absence of a dominant variant is a stronger signal than a high variant count. The backlog sorts on it.

---

## 8. Flag engine

Flags are the output. Keep them declarative and separate from extraction, in a rules file the field team can tune without a code change.

**Severity model.** Critical means it blocks stage 5 for the affected domain. Warning means it caps stage 3 or 4, or it materially degrades agent grounding. Informational means it scopes work or supports a business case.

**Confidence model.** Observed comes straight from the API. Derived required inference such as grouping or grain detection. Sampled came from a partial fetch such as permissions.

| Flag | Severity | Rule | Facet | Feeds |
|---|---|---|---|---|
| SEC-01 | Critical | Any calculated field formula contains USERNAME, ISMEMBEROF, FULLNAME, USERDOMAIN | Data entitlement | Security finding |
| SEC-02 | Warning | Content with explicit grants to All Users, or projects with permissive defaults | Governance preventive | Security finding |
| SEM-01 | Warning | Metric group variant count above threshold, default 5 | Semantic singularity | Variant table |
| SEM-02 | Critical | Metric group with no dominant variant and two or more variants carrying real usage | Semantic singularity | Variant table |
| SEM-03 | Warning | Field description coverage below 40 percent in scoped domains | Semantic describability | Variant table |
| SEM-04 | Warning | Published data source field count above 300 | Semantic exposure shape | |
| DF-01 | Warning | Embedded data source share above 60 percent | Semantic exposure shape | Variant table |
| DF-02 | Warning | More than 10 published sources tracing to one upstream table | Data provenance | Retirement case |
| DF-03 | Warning | Published source built on another published source, depth 2 or more | Data provenance | Retirement case |
| DF-04 | Warning | Published source with no traceable upstream | Data provenance | |
| DF-05 | Critical | Source whose last successful refresh exceeds twice its schedule interval AND is referenced by a workbook viewed in the last 30 days | Data freshness | Security finding |
| DF-06 | Warning | Extract refresh failure rate above 10 percent over the retention window | Data freshness | |
| DF-07 | Derived, warning | Custom SQL containing GROUP BY in the path to a scoped domain, or extract row counts far below upstream | Data retained grain | |
| GOV-01 | Warning | Published sources with no owner, or owner is a service account | Governance accountability | |
| GOV-02 | Informational | No data quality warnings configured anywhere | Data integrity | |
| EST-01 | Informational | Workbooks with zero views in 90 days | Adoption | Retirement case |
| EST-02 | Warning | Count of distinct users with edit rights on workbooks containing business-rule calculations | Semantic lifecycle | |
| ADO-01 | Warning | Active user penetration below 30 percent of licensed | Adoption | |
| ADO-02 | Informational | Workbooks accounting for 80 percent of views | Adoption | Retirement case |

The `Feeds` column maps each flag to the three field-facing findings, which is what the report generator uses to assemble the front page.

**Suppression.** DF-07 and EST-02 produce noise on large estates. Support per-flag thresholds and per-flag suppression in the rules file, and record suppressions in the run output so a report never hides a flag without saying so.

---

## 9. Facet scoring and rollup

Scoring turns flags and measures into facet scores, then rolls them up per decision domain.

### 9.1 Inputs

Scoring runs after the flag engine and consumes three things: flags for this run, the domain map, and the declared target stage per domain. Target stage comes from the run config, set by the specialist from what the customer declared in the maturity conversation. When no target is supplied, score every facet and emit no rollup, since readiness is meaningless without a target.

### 9.2 Facet score derivation

Each facet scores 1 to 6. Two derivation paths.

**Threshold facets.** A measure compared against the ordered bands in `rules.yaml`. The facet scores at the highest band whose condition holds.

```yaml
facets:
  semantic.singularity:
    dimension: semantic
    evidence: observed
    measure: dominant_variant_share      # share of scoped core metrics with a dominant variant
    bands:
      2: "< 0.4"
      3: "0.4 - 0.7"
      4: "> 0.7 and duplicates_deprecated == false"
      5: "> 0.7 and duplicates_deprecated == true and ratified == true"
      6: "estate_wide == true"
    gates: [5]                            # transitions this facet gates entry into
```

**Flag-capped facets.** Certain flags cap a facet regardless of its measure. A single critical flag is a hard ceiling.

```yaml
  data.entitlement_at_source:
    dimension: data
    evidence: observed
    caps:
      - flag: SEC-01
        when: "count > 0"
        max_score: 2
    gates: [5]
```

Emit `score`, `evidence`, `derivation` naming the band or cap that determined it, and `inputs` carrying the measure values. A score with no traceable derivation is not defensible when a customer asks.

### 9.3 Dimension rollup

Two rules, by dimension type.

**Supply and organizational dimensions.** Data, semantic, action surface, operating model, adoption, value. The dimension level is the minimum across facets gating entry into the target stage. Facets gating lower transitions, or gating nothing, are reported and do not cap.

```
gating_facets = [f for f in dimension.facets if target_stage in f.gates]
dimension_score = min(f.score for f in gating_facets)   # if empty, report ungated
```

**Governance.** Not a minimum. Evaluate loop closure. All five arcs must reach the tier the target stage demands. Governance scores at the highest stage whose loop closes completely.

```
for stage in descending(6..2):
    if all(arc.score >= required_tier(arc, stage) for arc in arcs if arc.active_at(stage)):
        governance_score = stage; break
```

Arc activation differs by stage and this is deliberate. Corrective is inactive below stage 5, since there is nothing to stop until agents act. Assurance activates at stage 3. Encode activation per arc in `rules.yaml` rather than in code.

### 9.4 Domain rollup

```
domain_readiness = min(dimension_score for all dimensions)
binding_constraint = the facet at that minimum, or facets if tied
gap = target_stage - domain_readiness
```

Ties are common and informative. Emit every facet at the minimum rather than picking one, since two simultaneous constraints change the remediation plan.

### 9.5 What scoring must never emit

No composite across domains. No average of dimension scores. No single site-level number. The output is a per-domain register, and a caller wanting one number is asking for the thing the framework refuses to produce.

Assert this in code. A test should fail if `findings.json` gains a top-level score field.

### 9.6 Contract

```json
{
  "facets": [{"id":"semantic.singularity","dimension":"semantic","score":2,
              "evidence":"observed","derivation":"band 2: dominant_variant_share 0.31",
              "inputs":{"dominant_variant_share":0.31},"gates":[5]}],
  "domains": [{"id":"claims_ops","target_stage":5,"readiness":3,"gap":2,
               "dimension_scores":{"data":3,"semantic":2,"governance":2},
               "binding_constraints":["semantic.consensus","governance.assurance"],
               "unscored_dimensions":["action_surface"],
               "confidence":"mixed"}]
}
```

`confidence` is `observed` when every gating facet came from the scan, `mixed` when any came from an interview, and `reported` when the binding constraint itself is interview-derived. The field guide's routing depends on knowing which.

---

---

## 10. Interview capture

About half the framework is not observable, and it includes the facets gating stage 5. Without an input path the tool produces a partial score sheet and the specialist maintains the rest in a spreadsheet, which means the register and the web app disagree with each other.

### 10.1 Model

Interview findings are a second input to the same store, in a separate table, joined at scoring time.

```sql
interview_responses(run_id, facet_id, score, evidence_note, source_role,
                    source_name, captured_at, captured_by, confidence)
```

`source_role` is the role that answered, meaning data platform lead, analytics leader, security, business sponsor, finance. `source_name` is optional and excluded from the presentation build. Never overwrite a scan-derived facet. Where both exist, the scan wins and the interview response is retained as corroboration or conflict.

**Conflicts are a finding.** When an interview claims a facet is stronger than the scan measured, emit `INT-01`, informational, recording both values. A customer asserting ratified definitions while the tie-out fails is exactly the situation the assessment exists to surface, and it should not be silently discarded.

### 10.2 Input path

Three ways in, one format.

A YAML file the specialist edits, `interview.yaml`, with one block per facet carrying score, note, and source role. This is the primary path and the only one the prototype needs.

A CLI subcommand for a guided pass, `estate_scan interview --run <id>`, walking the unobservable facets with the question text from the methodology spec's protocol and writing responses as it goes. Better during a live session than editing YAML.

The web app's capture form, writing to the same schema and exporting the YAML. Same surface as baseline capture, so build them together.

### 10.3 Scoring interaction

Run `scan` first, then `interview`, then `score`. Scoring reads both tables. A facet with neither source is `unscored` and appears in coverage with reason `requires_interview`.

A domain whose binding constraint is interview-derived renders differently in the report, stating the source role and the date. Present a reported constraint as an interview finding rather than as a measurement, since a customer will ask where the number came from and the honest answer strengthens the rest.

### 10.4 Consequence for the CLI

Three subcommands rather than one entry point: `scan`, `interview`, `score`, plus `report`. `scan` alone produces observable flags and no rollup. This is the free tier-one scan. The full assessment is all four.

---

---

## 11. Output

Five artifacts from one run.

**`findings.json`.** Machine-readable flags, facet scores, coverage, and run metadata. This is the interface to anything downstream, including a future product surface.

**`report.md`.** The customer-facing readiness report, rendered from the template. Front page assembles from the three findings. Coverage gaps render as their own section.

**`variants.xlsx`.** One sheet per metric group, with every variant, its resolved formula in readable form, usage rank, context, and owner. This is the working artifact for adjudication sessions and it is what the specialist actually uses.

**`report.html`.** A single self-contained web app with the findings embedded, for presenting in the room and leaving with the customer. Offline, no server, no build step, no composite score. Emitted in two redaction builds, working and presentation. Full specification in the report web app document.

**`run.log`.** Shards, retries, partial responses, suppressions, and timing. Needed for both debugging and defensibility when a customer questions a number.

Facet scoring reads thresholds from the same rules file as flags. Emit the binding facet per domain, never a composite score.

---

## 12. Multi-run comparison

Trajectory is a first-class output in the maturity framework, and customers will compare reports produced months apart.

### 12.1 Scope

Compare two runs on the same site. Not a time series, not a dashboard. A diff between a baseline run and a current run, answering what changed and whether the direction is right.

### 12.2 Command

```
estate_scan compare --baseline <run_id> --current <run_id>
```

Emits `comparison.json` and a comparison section in the web app, rendered only when a baseline exists.

### 12.3 What gets compared

| Category | Measure | Why it matters |
|---|---|---|
| Facet movement | Score delta per facet, with derivation for both | The remediation scorecard |
| Flag lifecycle | Resolved, new, persisting, with counts | Whether the plan is landing |
| Variant convergence | Variant count and dominance per scoped metric | The clearest signal adjudication worked |
| Estate drift | New unowned sources, new embedded sources, new workbook-layer security rules | Whether new debt is accruing faster than old debt clears |
| Coverage change | Measures newly available or newly missing | Guards against a false improvement |

### 12.4 The comparability guard

This is the part that matters, and the reason to specify it rather than let it emerge.

A diff is only valid when both runs are comparable. Before emitting anything, check and report:

- Same query set version. A different version means different measures and the diff is void for affected facets
- Same rules file version. A threshold change moves scores with no estate change
- Same domain map. A remapped domain is not the same domain
- Same adoption source. Admin Insights against repository are not comparable for usage measures
- Same grouping mode. Model-assisted against local grouping changes variant counts
- Same tool version

Any mismatch renders the affected comparisons as `incomparable` with the reason stated, rather than as a delta. A report showing semantic maturity improving because someone lowered a threshold is worse than no report.

### 12.5 Estate drift is the non-obvious output

Remediation reduces existing debt and it does not stop new debt from arriving. A customer who adjudicated eleven metrics while their teams published forty new embedded data sources has not improved, and the facet scores may not show it because the scoped metrics improved.

Emit new-debt counts separately from resolved-debt counts. Both directions, always, side by side.

---

---

## 13. Testing

**Fixtures over live sites.** Capture anonymized raw responses from a real estate once and replay them. The derivation logic changes constantly and cannot depend on site access.

**Formula resolution needs a hostile test set.** Cycles, twelve-deep chains, name collisions across data sources, caption references, and unicode field names. This is where correctness bugs will live.

**Golden report test.** A fixture estate with known expected flags, asserted end to end. Threshold changes should visibly diff.

**Scale test.** Synthesize a fifty-thousand-field estate and confirm the field extraction stage completes and resumes correctly. Do this before the first large-account run, not after.

**Partial-response test.** Force a node limit and assert the tool subdivides rather than accepting the truncated data. Highest-value test in the suite.

---

## 14. Open decisions

**Domain scoping input format.** The tool needs a domain map and the methodology spec offers four mechanisms. Recommend a simple CSV of project or workbook identifier to domain, generated semi-automatically and hand-corrected, since anything more sophisticated will not survive contact with real project hierarchies.

**Where dominance thresholds get calibrated.** They are guesses today. Instrument the tool to emit the distribution of variant counts and dominance ratios per run, collect across the first several engagements, and set thresholds from data rather than intuition.

**Migration path into product.** Knowledge's graph health and health scoring covers overlapping ground. Keep `findings.json` stable and vendor-neutral so this tool becomes either a pre-purchase complement or an input to that surface rather than a competing artifact.

**Redaction defaults.** Decide before external use whether formulas leave the customer machine at all. My recommendation is that they do not, and that only counts, hashes, and structural measures are portable.
