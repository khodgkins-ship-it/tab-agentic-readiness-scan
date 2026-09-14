# Estate Scan Report Web App

## Specification

One of the five output artifacts defined in the tooling build spec, alongside `findings.json`, `report.md`, `variants.xlsx`, and `run.log`.

---

## 1. What it is and what it is not

A single self-contained HTML file emitted by the `report/` module with the run's findings embedded. It opens from the filesystem, works offline, and needs no server.

**It is a presentation instrument and a working tool, in that order.** The specialist and AE present from it in the room after the maturity conversation, then leave it with the customer. The customer reopens it when they socialize the findings internally, which is where most of the commercial work actually happens, since the person who has to fund remediation is usually not in the original meeting.

**It is not a dashboard.** It has no live connection, no refresh, and no composite score.

### The constraint that shapes everything

**No overall maturity score, and no gauge.** Every version of this framework refuses a composite, because averaging hides the binding constraint the assessment exists to find. A dashboard naturally wants a big dial on the cover, and building one would undo the model's central design decision in a single UI element. The cover carries the current stage, the target stage, and the binding constraint. Three facts, no synthesis.

---

## 2. Technical constraints

**Single file.** One `.html` with CSS and JS inline and the findings embedded as JSON in a script tag. No adjacent assets, no imports.

**Fully offline.** No CDN, no external fonts, no network calls of any kind. It will open on a customer laptop in a conference room with guest wifi, and in a room with no wifi. A CDN dependency means a blank page in front of the customer.

**No build step.** Vanilla HTML, CSS, and JS. Consistent with how the metadata explorer repo handles its frontend, and it keeps the report module free of a toolchain.

**Print and PDF.** A dedicated print stylesheet. Customers will circulate this as a PDF regardless of what we intend, so make the print output deliberate rather than accidental. Presenter chrome hides, all sections expand, page breaks fall between sections.

**Size ceiling.** Target under 5 MB. A large estate produces tens of thousands of field records, so the app embeds derived and aggregated data plus the variant detail for scoped metrics, never the raw extract. If the payload approaches the ceiling, drop unscoped variant detail first.

**Accessibility floor.** Keyboard navigable, real headings, sufficient contrast, and no meaning carried by color alone. This gets presented on a projector in a bright room, which is its own argument for high contrast.

---

## 3. Two modes, one dataset

A toggle in the header, defaulting to Present.

**Present.** Large type, one finding per view, progressive reveal. Built for a projector and for a conversation where the specialist controls pacing. Keyboard navigation with arrow keys. Nothing auto-expands.

**Explore.** Dense, searchable, everything drillable. Built for the specialist working the estate afterward and for the customer's own team digging in.

Same embedded data, two renderings. Do not build two payloads.

---

## 4. Structure

Ordered to match the field motion rather than the document. The three findings lead, because they carry the commercial work and each speaks to a different buyer.

### 4.1 Cover

Customer name, scan date, scan window, estate profile classification, and the three facts: current stage, target stage as the customer declared it, binding constraint.

One line stating what the scan measured and what it did not, linking to the coverage panel. This appears on the cover rather than in an appendix on purpose.

### 4.2 Finding one, definition multiplicity

The primary artifact in the whole app, and the thing that does the persuading.

Top level is the metric table. Metric name, variant count, workbooks affected, count materially disagreeing, and variants covering 80 percent of views. Sortable, and sorted by default on absence of a dominant variant rather than on raw variant count, since that ordering matches the real difficulty.

Click a metric to drill into its variants. Each variant shows the resolved logic in readable form, usage rank with view and workbook counts, the context it assumed meaning sheet and filters and audience, the owner, and the downstream reports consuming it. Where material disagreement was tested, show the two numbers for the same period side by side, which is the single most persuasive element available.

Visual treatment: a simple horizontal bar of usage share across variants makes dominance or its absence immediately legible. Resist anything more elaborate.

### 4.2a Severity treatment across the three findings

All three findings render in neutral chrome. Same border, same surface, no color coding by severity at the top level.

Severity appears on drill-down, where the specific flag carries its own treatment.

The reason is audience rather than aesthetics. Coloring the security count as urgent is correct for an IT or security buyer and reads as an accusation to the analytics leader whose estate produced it, and the analytics leader is usually the person in the room. Neutral presentation lets the specialist assign weight verbally, per audience, rather than the artifact assigning it for them in every meeting.

This also protects the three-buyer structure. Each finding speaks to a different person, so pre-ranking them on the page undercuts the reason there are three.

### 4.3 Finding two, security exposure

Count of access rules enforced in the visualization layer, the workbooks and domains they cover, and a plain statement of what happens when a programmatic query bypasses them. Drill to the affected workbook list with owners.

Keep this section blunt and short. It is aimed at a security or IT buyer who wants the exposure and the remediation, not a narrative.

### 4.4 Finding three, retirement case

Total content against content viewed in the window, the concentration figure, and the count of unused workbooks and redundant sources. Present it as recoverable capacity rather than as waste, since the buyer here owns the analytics budget and this is the argument that funds the rest without new money.

### 4.5 Readiness by dimension

Seven dimensions, each with its score, evidence level, whether it gates the declared target, and a one-line finding. The binding constraint is visually distinct. Expand any dimension for its underlying flags and measures.

Evidence level renders as a visible attribute, not a footnote. Adoption scored from telemetry and governance scored from an interview are not equally derived, and the customer should see which is which.

### 4.6 Readiness register

One row per decision domain. Target, current, binding constraint, failed demonstration, first move. Expand a domain for its per-facet detail and the value the transition produces.

### 4.7 Remediation and cost to gate

Phases with effort, owner, and the transition each is charged to. The attribution rule stated visibly, so nobody double counts definition adjudication across two transitions. A deliberately visible list of what is out of scope, since that list is what keeps the plan fundable.

### 4.8 Baseline capture

Editable in the app, with export.

Field practice calls baseline capture the cheapest and most perishable work in the program, and it happens during interviews. A form that captures it while the room is together, rather than a table someone fills in afterward from memory, is worth the small amount of build effort.

Six to eight measures with current value, source, and date. Values persist to `localStorage` keyed by run identifier so a reopened file retains them, with an explicit export to JSON and CSV since browser storage is not a system of record. Say so in the interface.

### 4.9 Coverage panel

Persistently reachable from the header, not buried.

Every measure the scan attempted, with status and the reason anything failed. A scan that skipped freshness because job history was unavailable must not be readable as a clean freshness result, and a UI makes that omission easier to hide than a document does. This panel is the counterweight.

Include the run metadata: tool version, query set version, scan timestamps, grouping mode meaning local or model-assisted, and the sampling basis for permissions.

---

## 5. Interaction worth building, and interaction to refuse

**Build.** Variant drill-down. Cross-linking from a flag to the affected objects. Search across metrics, workbooks, and sources in Explore mode. Sort on any table column. Copy any table to clipboard, since people will want figures in their own decks. Per-section print.

**Refuse.** Any composite score, dial, or gauge. Animated transitions, which read as vendor polish and cost credibility in a diagnostic. Charts that restate a two-row table. A lineage graph, which the metadata explorer already does well and which would inflate the payload for a visual nobody decides from. Anything requiring a network call.

---

## 6. Redaction builds

The web app is the artifact most likely to leave the customer's control, since it is a single file and easy to email. That makes redaction a build-time decision rather than a runtime toggle, because a runtime toggle in a shared file protects nothing.

Two builds from the same run.

**Working build.** Full detail including resolved formula text, owner names, and workbook names. Stays with the specialist and the customer's analytics team. Filename marked, and a visible banner in the interface stating it contains business logic.

**Presentation build.** Counts, rankings, disagreement figures, metric and source names. No formula text, no individual owner names, workbook names optional per customer preference. This is the one that circulates.

Default the CLI to emitting both, with the presentation build as the one the report module names in its console output. Record in the run log which builds were produced.

Neither build ever contains credentials, tokens, or connection strings. Add a pre-emit scan asserting this and fail the build on a hit rather than warn.

---

## 7. Implementation notes

Template rendering happens in the `report/` module. Keep the HTML, CSS, and JS as separate source files under `report/webapp/` and concatenate at emit time, so the app is maintainable in development and single-file in output.

The embedded payload is a documented schema, and it should be a subset of `findings.json` rather than a parallel format. One source of truth for findings, two consumers.

Version the app template independently of the tool and record its version in the run metadata, since a customer will eventually compare two reports produced months apart.

**Testing.** Snapshot the rendered HTML against a fixture run. Assert the presentation build contains no formula text, which is a correctness test rather than a style test. Verify it opens from `file://` with the network disabled, which is the failure nobody catches until it happens in a customer meeting. Confirm the print output on one long and one short run.

---

## 8. Open question

Whether the app should offer a mode that presents the findings without the maturity framing, meaning the three findings, the coverage panel, and the remediation plan, with no stages and no scores.

The argument for it: the field guide is explicit that the maturity model belongs in conversation rather than in an artifact, and some customers will receive the stage language as a verdict on them. A findings-only build sidesteps that entirely.

The argument against: the stages are what make the remediation plan feel purposeful rather than like a list of chores, and removing them may weaken the plan's rationale.

My recommendation is to build the framing-light mode and let the field choose per account, since the cost is a conditional render and the downside of the wrong framing in a sensitive account is a stalled conversation.
