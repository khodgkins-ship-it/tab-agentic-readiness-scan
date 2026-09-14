# Tableau Estate Scan

Specification set for a tool that reads a Tableau estate through its APIs and produces an agentic analytics readiness assessment.

## Read in this order

**`01-maturity-framework-reference.md`**
The framework the assessment scores against. Six stages, seven dimensions, gating rather than averaging, and behavioral demonstrations at each gate. Sections 1 through 4 are the parts the tooling depends on.

**`02-assessment-methodology.md`**
What to measure and why. Probe catalog mapped to framework facets, domain scoping, the definition multiplicity method, material disagreement testing, scoring thresholds, and the interview protocol for what no API can see.

**`03-tooling-build-spec.md`**
How to build it. Architecture, authentication, deployment capability detection, extraction, data model, derivation algorithms, flag engine, facet scoring, interview capture, outputs, multi-run comparison, and testing.

**`04-report-webapp-spec.md`**
The single-page web app output artifact. Offline, self-contained, two redaction builds, no composite score.

**`05-metadata-explorer-reuse.md`**
What `tableau/tableau-metadata-explorer` already provides, what to reuse, what to reject, and why the assessment pipeline stays separate from that repo's application layer.

**`06-build-brief.md`**
The work order. Prototype scope, repo layout, seven milestones with acceptance criteria, decisions already made, and what not to decide alone. Start here once the rest is read.

## Principles running through all of it

No composite maturity score, in any artifact or interface. Averaging hides the binding constraint the assessment exists to find.

Readiness is relative to a declared target stage, set per decision domain rather than site-wide.

Gates require behavioral demonstration rather than deployment evidence.

Queries are fixed and versioned, never generated at runtime, so findings are comparable across reruns and across accounts.

Coverage is a first-class output. An unmeasured dimension must never read as a clean one.

Local-first data handling. Model assistance is opt-in, recorded in run metadata, and never authors a metric definition.

Read-only against Tableau, enforced in code.
