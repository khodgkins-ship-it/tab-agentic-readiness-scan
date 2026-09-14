# Tableau Estate Readiness Assessment

## Assessment Methodology

Internal document for the team running the assessment. The customer-facing output is the readiness report template.

---

## 1. What this produces

Three artifacts.

A **facet score sheet**, one row per facet from the maturity model, each carrying a score of 1 to 6, an evidence level, and the probe or interview it came from.

A **readiness register**, one row per decision domain, with target stage, current readiness, binding constraint, and first move.

A **variant inventory**, the metric-by-metric list of competing definitions ranked by usage, which becomes the working input to definition adjudication.

The scan does not produce a readiness verdict on its own. It scores the observable facets, scopes the remediation, and tells you which interviews matter.

---

## 2. Prerequisites

| Requirement | Notes |
|---|---|
| Metadata API access | Site administrator or server administrator. Confirm the Metadata API is enabled, since it is off by default on some Server deployments |
| REST API access | Personal access token with admin scope, for permissions, refresh schedules, and job history |
| Admin Insights | Site administrator. Cloud only. On Server, substitute the repository or a Server Insights equivalent |
| Query execution path | Needed for material-disagreement testing. VizQL Data Service, or warehouse access with the ability to run representative variants |
| Named customer contacts | One data platform owner, one analytics leader, and one business owner per target domain |
| Scope agreement | The domain-to-content mapping from section 3, signed off before scanning |

Validate every object and field name in this spec against the current Metadata API schema before building. Names change between releases, and several probes depend on fields whose availability differs between Cloud and Server.

---

## 3. Domain scoping, do this first

The maturity model scores per decision domain. An estate scan returns estate-wide results. Bridging the two is the step most likely to break the assessment, and it has to happen before any query runs.

Pick the mapping mechanism in this order of preference.

1. **Project hierarchy.** Where projects correspond to business domains, map project to domain directly. Cleanest and least common.
2. **Content tags.** Where the customer tags workbooks or data sources by function.
3. **Owner and group membership.** Map content owner to their business unit through group membership. Workable, and noisy where a central analytics team owns everything.
4. **Manual mapping of the active set.** Map only the workbooks accounting for the top 80 percent of views, typically a few hundred rather than thousands. Slowest and most reliable.

Record which mechanism you used, since it determines how much confidence to attach to domain-scoped scores. Estate-wide findings hold regardless. Domain-scoped findings inherit the mapping quality.

**Unmappable content.** Expect 10 to 30 percent of content to resist mapping. Report it as a separate line rather than distributing it, since an unmappable workbook is itself a governance finding.

---

## 4. Probe catalog

Each probe carries an ID, the facet it scores, its source, and its evidence level. Probes marked Observed produce a score directly. Probes marked Derived need human validation. Facets with no probe are interview-only, listed in section 7.

### 4.1 Data foundation

**DF-01. Connectivity and federation** · Data reach · Observed

Count distinct upstream databases and connection types per domain. Count published data sources drawing on more than one upstream database.

```graphql
{
  publishedDatasources {
    name
    luid
    projectName
    upstreamDatabases { name connectionType }
    upstreamTables { name schema }
  }
}
```

Derived: distinct upstream database count per domain, and the share of domain content reachable through a single addressable surface.

**DF-02. Retained grain** · Data reach · Derived

Find aggregation in the path. Three signals, in descending reliability.

- Custom SQL containing GROUP BY, feeding published data sources
- Extract-based data sources whose row count is orders of magnitude below the upstream table
- Field naming patterns indicating pre-aggregation, such as monthly, weekly, and total prefixes on measure names

```graphql
{
  customSQLTablesConnection(first: 500) {
    nodes {
      query
      downstreamDatasources { name luid }
      columns { name }
    }
  }
}
```

Derived: for each domain, classify as transaction grain, rollup with atoms available upstream, or rollup with atoms discarded. **The third case is not determinable from Tableau metadata.** It requires a conversation with the pipeline owner, since Tableau sees only what reached it. Distinguishing these two matters more than any other output of DF-02, because remediation cost differs by roughly an order of magnitude.

**DF-03. Entitlement at source** · Data reach · Observed

Search calculated field formulas for user-context functions.

```graphql
{
  calculatedFieldsConnection(filter: {formula: {contains: "USERNAME"}}, first: 1000) {
    nodes {
      name
      formula
      datasource { name luid }
      ... on CalculatedField { referencedByFields { name } }
    }
  }
}
```

Run for USERNAME, ISMEMBEROF, FULLNAME, and USERDOMAIN. Cross-check REST API for data source level user filters and row-level security configuration.

Derived: count of visualization-layer access rules, and the domains they cover. This is the highest signal-to-effort probe in the catalog. Any non-zero count blocks stage 5 for the affected domain.

**DF-04. Integrity and quality** · Fidelity · Observed, partial

Count data quality warnings in use, certified data sources, and data sources with a certification note. Note the limit plainly: upstream testing, whether dbt tests, warehouse constraints, or pipeline validation, is invisible to Tableau. Treat DF-04 as a partial signal and complete it by interview.

**DF-05. Provenance and lineage** · Fidelity · Observed

Three derived measures.

- Fan-out: count of published data sources tracing to the same upstream table
- Stacking: published data sources whose upstream is another published data source, with depth
- Orphans: published data sources with no traceable upstream table

```graphql
{
  publishedDatasources {
    name
    luid
    upstreamTables { id name }
    upstreamDatasources { name }
    downstreamWorkbooks { name luid }
  }
}
```

**DF-06. Freshness** · Liveness · Observed

From REST API job and task history rather than the Metadata API.

- Extract refresh failure rate over 30 days
- Count of data sources whose last successful refresh exceeds their schedule interval by more than 2x
- Count of stale data sources still referenced by workbooks with views in the last 30 days

The last measure is the one to lead with. A stale source nobody uses is housekeeping. A stale source feeding an active dashboard is a live wrong-answer risk.

**DF-07. Drift management** · Liveness · Interview

Not observable. Upstream schema contracts live outside Tableau. One weak proxy: workbooks with field-not-found or broken-reference errors indicate drift already landing.

**DF-08. Stewardship** · Liveness · Observed

Owner attribution and certification coverage on published data sources. Note that Tableau content ownership is often a publishing artifact rather than accountability. Confirm by interview whether named owners know they are owners.

### 4.2 Semantic layer and ontology

**SEM-01. Describability** · Legibility · Observed

```graphql
{
  fieldsConnection(first: 5000) {
    nodes {
      name
      description
      ... on ColumnField { dataType role }
    }
    totalCount
  }
}
```

Derived: share of fields carrying a description, share of published data sources with a description, and a cryptic-name rate. Score cryptic names by pattern, meaning names under four characters, names containing version suffixes, and names matching known abbreviation patterns.

**SEM-02. Definition multiplicity** · Legibility, singularity · Derived

The flagship probe. Section 5 covers the method, since it needs more than a query.

**SEM-03. Exposure shape** · Legibility · Observed

- Published to embedded data source ratio
- Field count per data source, flagging sources above roughly 300 fields as schema-overload candidates
- Certified share of published sources
- Count of workbooks per published data source, as a reuse measure

**SEM-04. Consensus and correctness** · Trust · Interview

Not observable, and this is the binding facet for most long-tenured customers. Section 7 has the protocol. Do not let a high SEM-01 score stand in for this. Complete documentation of 47 conflicting definitions is excellent legibility and zero consensus.

**SEM-05. Lifecycle and change control** · Trust · Derived

Partial observability. Revision history exists on Tableau content, so you can measure change frequency on the data sources and calculations feeding target domains. Certification staleness is observable, meaning certified sources whose underlying schema changed after certification.

What is not observable: whether a change was reviewed, by whom, and against what criteria. Interview.

**Additional derived measure worth taking.** Edit surface, meaning the count of distinct users holding edit rights on the workbooks containing business-rule calculations an agent reads. With the knowledge graph exposing those calculations live, this number is the size of the ungoverned change surface.

**SEM-06. Composability** · Trust · Observed

Reuse depth per published data source, and the share of target-domain fields sourced from certified shared models rather than workbook-local calculations.

**SEM-07. Structure and ontology** · Structure · Derived

Partial. Relationships defined in the data source logical layer are observable and distinguishable from physical joins. Entity constraints and cross-domain identity resolution are not. Interview.

### 4.3 Action and integration surface

Mostly not observable from Tableau metadata, since actions execute in Flow, Agentforce, or external systems. Observable pieces:

- Extensions and external action surfaces configured on dashboards
- Data Cloud activation targets, where in use
- Whether any write-back path exists at all

Everything on reversibility classification, atomicity, idempotency, and blast radius limits is interview. Score conservatively. For a read-only estate, this dimension scores 2 and the interview confirms rather than discovers.

### 4.4 Governance and trust

**GOV-01. Preventive** · Observed, partial

Project permission structure, locked permissions coverage, count of projects with permissive default grants, and count of content with explicit grants to All Users. Risk tiering of decisions is interview.

**GOV-02. Detective** · Observed, partial

Whether activity logging or Admin Insights is in active use, and whether anyone consumes it, measurable as views on admin content. Agent-specific decision logging is interview.

**GOV-03. Corrective** · Interview

Not observable.

**GOV-04. Accountability** · Derived

Owner coverage from DF-08 and GOV-01, validated by interview against whether accountability appears in objectives.

**GOV-05. Assurance** · Interview

Not observable, and gating from stage 3. Section 7 has the protocol.

### 4.5 Adoption and decision culture

**ADO-01 through ADO-04** · Observed · Admin Insights

- Active users, and penetration against licensed users, by function
- View concentration, meaning the count of workbooks accounting for 80 percent of views
- Stale content, meaning workbooks with zero views in 90 days
- Feature adoption for conversational and proactive analytics, separating enablement from consistent use

Decision culture itself, meaning whether teams act on insight and whether approvers examine, is interview.

### 4.6 Value realization

Interview only. No probe.

---

## 5. Definition multiplicity, method

This probe carries the assessment. It also fails quietly if done carelessly, so the method matters.

**Step 1. Extract.** Pull every calculated field with its formula, its containing data source or workbook, and its reference count.

```graphql
{
  calculatedFieldsConnection(first: 5000) {
    nodes {
      name
      formula
      datasource { name luid }
      referencedByFields { name }
      referencedBySheets { name workbook { name luid } }
    }
  }
}
```

**Step 2. Resolve references.** A calculation referencing another calculation is not comparable until both are resolved. Recursively inline referenced calculated fields until each formula is expressed in base columns. Cap recursion depth and log cycles, which do occur.

**Step 3. Normalize.** Strip whitespace and comments, lowercase, standardize field-reference bracketing, and normalize numeric literal formatting. Do not normalize away filter conditions or date logic, since those are usually the substance of the difference.

**Step 4. Group by concept.** Formula clustering finds identical logic. Concept grouping finds the same metric under different names, meaning Revenue, Total Revenue, Net Rev, and Rev USD. Do this with AI assistance and human confirmation. The customer's business owner confirms the grouping.

**The guardrail, stated in the customer report and worth repeating here.** Use AI to group variants and to draft documentation. Never use it to author the authoritative definition. Auto-generating a definition from ambiguous source logic produces a semantic layer encoding the ambiguity while looking authoritative, which is worse than having none.

**Step 5. Rank by usage.** Attach reference counts and view counts per variant. Report the number of variants covering 80 percent of consumption alongside the raw variant count. Raw counts identify the scale of the problem. Usage-weighted counts identify the work, and the two often point at different metrics.

**Step 6. Test material disagreement.** Execute representative variants against a common period and compare results. Needs a query execution path and cannot be done from metadata alone. Section 6 specifies this in full.

Report per metric: variant count, workbook count, materially disagreeing count, variants covering 80 percent of views, and whether a dominant variant exists.

**Interpretation rule.** A metric with many variants and one dominant well-used definition is a fast adjudication. A metric with fewer variants and no dominant candidate is the hard one. Sort the adjudication backlog by absence of a dominant variant, not by variant count.

---

## 6. Material disagreement testing

This produces the number that does the most persuading, so it is specified in full.

### 6.1 What it establishes

That two variants of the same metric return different values for the same period, and by how much. Everything else in the variant finding is structural. This is the only part that proves consequence.

### 6.2 Preconditions

Runs in `--mode=full` only, never unattended, always with a customer analyst present. Requires a query execution path and a defined period.

### 6.3 Execution path

Prefer VizQL Data Service against the published data source containing the variant, since it honors Tableau semantics and the requesting user's entitlements, and therefore returns what the agent would see.

Fall back to direct warehouse execution only where a variant resolves cleanly to base tables, and record the fallback, because a warehouse result and a VizQL result can diverge and the divergence is itself worth knowing.

### 6.4 Variant executability

Not every variant can be tested, and pretending otherwise produces false clean results. Classify each before attempting.

| Class | Condition | Handling |
|---|---|---|
| Executable | Resolves to fields present in a queryable published source | Test |
| Context-bound | Requires filters or parameters from its containing sheet | Test with the recorded context applied, and record that the context was applied |
| Unresolvable | References fields absent from any queryable source, or resolution failed | Not tested. Report as untested with the reason |
| Not comparable | Different grain from the group's reference variant | Not tested. Report as a grain difference, which is itself a finding |

Report tested, untested, and the reason distribution. A metric where most variants are unresolvable is a finding about estate legibility, not an absence of disagreement.

### 6.5 Period and tolerance

**Period.** One recent complete period, chosen with the customer, and the same period across every variant of every metric in the run. Record it. A month is usually right, and a partial current period is not.

**Tolerance.** The customer sets it, per metric, before results are shown. This ordering matters. A tolerance agreed after seeing the numbers is an argument rather than a criterion.

Default proposal of 0.5 percent relative difference, with an absolute floor so small denominators do not produce spurious flags. Metrics feeding external reporting usually warrant tighter. Record the tolerance and who agreed it.

**Material** means exceeding tolerance against the group's reference variant, which is the dominant one where it exists and the highest-usage one where it does not. Every comparison is pairwise against that reference, not all-pairs, since all-pairs produces a matrix nobody reads.

### 6.6 Output

Per metric: reference variant, and for each tested variant the value, the absolute and relative difference, material true or false, and the context applied. Plus counts of untested variants by reason.

The report renders the two values side by side for the most material pair. That single comparison is the most convincing element the tool produces, and it needs no chart.

### 6.7 Handling and safety

Read-only queries only. Log every executed statement and the connection identity used. Never store returned business values in the presentation build, and treat them as customer data in the working build. Two revenue figures for one month is sensitive, and the finding needs the difference rather than a durable copy of the numbers.

---

---

## 7. Scoring thresholds

Provisional. Calibrate against the first five engagements and expect to move them.

| Facet | Score 2 | Score 3 | Score 4 | Score 5 | Score 6 |
|---|---|---|---|---|---|
| Describability | Under 10 percent of fields described | 10 to 40 percent | 40 to 70 percent | Over 70 percent in target domains, keys documented | Estate-wide |
| Singularity | Dominant variant absent on most core metrics | Dominant variant on most, duplicates live | One definition per core metric, duplicates deprecated | Ratified single definition, no live duplicates in domain | Estate-wide |
| Exposure shape | Embedded over 70 percent | 40 to 70 percent | Under 40 percent, domain models exist | Atomic grain exposed, domain-bounded, entitled | Composed across domains |
| Entitlement at source | Any workbook-layer rule in domain | Central policy exists, workbook rules remain | No workbook rules, policy partial | Enforced at query compile, zero workbook rules | Held |
| Provenance | No lineage | Lineage present, high fan-out | Fan-out reduced, stacking removed | Every domain source traced and validated | Held |
| Freshness | Recency unknown | Monitored, failures over 10 percent | Failures under 5 percent | Stated service level, recency reaches the agent | Held |
| Composability | Single-use sources | Some reuse | Domain models reused | Certified, versioned, reused across agents | Shared entity model |

Facets scored by interview use the maturity framework criteria directly rather than a threshold table, since there is nothing to threshold.

**Rollup.** Per domain, take the minimum across facets gating entry to the target stage. Governance rolls up by loop closure at the target tier, not by minimum. Record the binding facet, since it is the deliverable.

---

## 8. Interview protocol for what the scan cannot see

Roughly half the framework is not observable, and it includes the facets gating stage 5. Budget as much time here as for the scan.

**Semantic consensus.** Per core metric: who owns this definition, meaning the business owner rather than the analytics team. Has anyone ratified it. What happens when two functions disagree. Who signs a change. Ask the same question of two functions separately and compare answers, which surfaces unrecognized disagreement faster than asking a room.

**Assurance.** Do you measure whether the agent is right. Show me the question set. What threshold did the last domain clear before it went live. When a definition changed last quarter, how did you know whether it helped.

**Governance corrective.** When an agent recommendation is wrong today, what stops it. Who is paged. What is the reversal path.

**Action surface.** Walk me through one action you intend to delegate. What does the reversal look like. What happens if it runs twice.

**Operating model.** Who owns each semantic model, by name. Is it in their objectives. What happens to your 14 analysts' current workload when they start modeling knowledge instead.

**Decision culture.** Pull 90 days of approval decisions and look at the rejection pattern. This is technically observable where the approval surface logs decisions, and it is the strongest cultural measurement available. An approval rate above 95 percent with no pattern behind the rejections means approvers are clicking.

**Value.** What outcome does this domain own. What is the current baseline. Who reports it.

---

## 9. Run sequence and effort

| Stage | Effort | Output |
|---|---|---|
| Access and scope agreement | 2 to 3 days elapsed | Credentials, domain mapping |
| Extraction | 1 day compute, run off hours on large estates | Raw metadata, permissions, refresh history, Admin Insights extracts |
| Derived analysis | 3 to 4 days | Variant inventory, lineage measures, scored observable facets |
| Material disagreement testing | 2 days, needs a customer analyst | Tie-out results per core metric |
| Interviews | 2 weeks elapsed, 8 to 12 sessions | Interview-scored facets |
| Register and report | 3 to 4 days | Readiness register, report, remediation plan with cost to gate |
| Baseline capture | Parallel with interviews | The section 7 baseline table, dated |

Four to six weeks elapsed, roughly three person-weeks of effort.

**Rate limiting.** Metadata API pagination on estates above a few thousand workbooks needs cursor-based paging with retry. Budget for a run that takes hours, and cache raw responses so derived analysis reruns without rescanning.

**Baseline capture is perishable.** It becomes unavailable once remediation starts. Take it during interviews, not after.

---

## 10. Known limits

**The scan measures existence and multiplicity, not correctness.** Every facet gating stage 5 sits outside it. State this in the report before presenting findings.

**Domain scoping quality caps domain-scoped confidence.** Estate-wide findings are solid regardless.

**Grain remediation cost is not determinable from Tableau.** Whether atoms exist upstream requires the pipeline owner.

**Upstream quality practice is invisible.** Warehouse tests, contracts, and pipeline validation do not surface.

**Content ownership is often a publishing artifact.** Never score accountability from owner fields alone.

**Thresholds in section 6 are provisional.** Track the distribution of scores across engagements and recalibrate. A threshold set placing every customer at 3 is measuring nothing.

**Prefer a smaller scan.** Every probe in this catalog maps to a facet. Add nothing that does not, since an estate report full of interesting unactionable metrics reads as thorough and changes no decision.
