# Agentic Analytics Maturity and Readiness Model

## What this model does

It answers four questions, and keeps them separate.

**Maturity.** How much of the path from data to action have you delegated to agents today?

**Readiness.** What stands between you and the stage you intend to reach?

**Trajectory.** Are you progressing, holding, or slipping?

**Value.** Is any of it producing measurable business results?

Those four come apart in practice. An organization early on the curve is often healthy and successful. A technically sophisticated one is sometimes in trouble. Reporting a single number hides both cases.

Technology enables maturity. Technology adoption does not define it. You do not advance by purchasing a capability, and every stage in this model requires evidence rather than deployment.

---

## Part 1. The curve

Six stages. Each one answers three questions: who initiates, who decides, who acts.

### Stage 1. Minimal — FIND

Analytics is dashboards and reports. People find, filter, and interpret on their own.

- Business context lives with the person, not the system
- Metric definitions vary across teams
- Analytics sits outside daily workflows
- Usage concentrates among analysts
- Business outcomes are anecdotal

### Stage 2. Emerging — ASK

People ask questions in plain language and explore governed data conversationally.

- Natural language replaces some dashboard navigation
- Shared definitions ground answers for important metrics
- Analytics reaches beyond analysts to business users
- People investigate what happened and start asking why
- Adoption is measured, and outcomes begin to be defined

### Stage 3. Performing — UNDERSTAND

The system understands the business context around a question, not only the question.

- Trusted semantic models supply definitions, relationships, and meaning
- Context persists across questions
- Analytics explains drivers and why a change matters
- Insights arrive inside CRM, Slack, applications, and other work surfaces
- Outputs are governed and traceable
- Agent accuracy is measured against known answers, not assumed
- Defined outcomes are measured and attributable

### Stage 4. Optimizing — RECOMMEND

Analytics stops waiting to be asked. Agents monitor what matters and surface findings unprompted.

- Agents watch metrics, goals, and business signals continuously
- Insights are personalized by role, objective, and workflow
- Anomalies, drivers, risks, and opportunities surface without a question
- Recommendations connect what changed, why it matters, and what to do next
- People move from insight to action inside one workflow
- Value is tied to specific analytical interventions

### Stage 5. Leading — ACT

Agents execute inside guardrails. A person approves each action.

- Agents reason across data, business knowledge, goals, and constraints
- Predictive, simulation, and prescriptive analytics evaluate options
- Agents take action in systems of record, and a person approves
- Actions are reversible by default, or carry a defined recovery path
- Every recommendation and action is explainable and traceable
- Business outcomes attributable to agent action are measured

### Stage 6. Autonomous — OPERATE

Agents act under policy. People supervise exceptions rather than approve transactions.

- Policy, expressed as code, replaces per-decision approval
- Automatic halt, rollback, and circuit breakers stop a bad action without a person
- Agents coordinate with each other across domains
- Exception review is a standing operating rhythm
- Outcomes feed back and improve future decisions
- Analytics is optimized against business results rather than usage

### Higher is not automatically better

Stage 6 is the right target for reversible, high-volume, low-consequence decisions. Stage 5 is often the right permanent home for anything regulated or expensive to undo. A mature organization keeps consequential decisions under human approval on purpose, and sets its target per decision domain rather than enterprise-wide.

Calibrate ambition against what the frontier has reached. The published accounts of internal analytics agents at Anthropic and OpenAI describe systems answering questions, running queries, and producing analysis, with people deciding and acting. Two organizations building on their own frontier models are operating at Ask and Understand. Stage 3 executed well, with measured value, beats stage 5 announced and unproven.

### Two transitions cost far more than the others

**Stage 4 to 5.** Below it, a flawed metric definition produces a wrong chart your analyst catches. Above it, the same definition produces a wrong action with nobody in the path. A misdefined "active customer" stops being a reporting discrepancy and starts issuing credits and routing cases.

**Stage 5 to 6.** Human approval is your brake. Removing the approver means building a replacement in software first. Most programs that get hurt get hurt here, with observability mature and the corrective controls still manual.

---

## Part 2. Seven dimensions

Your stage on the curve is the outcome of the assessment. These seven dimensions produce it.

**1. Data foundation.** Whether agents reach data that is correctly shaped, accurate, traceable, and current. Three concerns: reach, meaning one addressable surface with transaction-level detail retained and permissions enforced at the source. Fidelity, meaning quality and lineage hold. Liveness, meaning it stays correct as it flows, with stated freshness levels, schema contracts, and named stewards. Reach problems announce themselves. Liveness problems stay silent, and an agent has none of a person's instinct to ask why revenue reads zero.

**2. Semantic layer and ontology.** Your semantic layer defines what your numbers mean. Your ontology defines how your business is put together and which states are valid. The first produces correct answers. The second produces correct reasoning about situations nobody wrote down. Semantics carry you to stage 5. Ontology becomes load-bearing at stage 6, when agents cross domains and traverse relationships no one specified for that case.

Two sources of meaning get overlooked. Business context, meaning launches, incidents, internal names, org structure, and the reason a question is being asked. An agent without it answers what someone asked rather than what they meant. And transformation code, where a table's real meaning lives. Pipeline logic carries assumptions, exclusions, and freshness guarantees appearing nowhere in a schema or a data dictionary.

**3. Action and integration surface.** Two concerns. Reach, meaning insights and actions arrive in the systems where work happens. Containment, meaning actions complete or unwind cleanly, every action is classified as reversible or compensating, and blast radius is capped. Containment is what your approver was providing at stage 5.

**4. Governance and trust.** A control loop, not a ladder. Five parts, all required. **Preventive**, defining what an agent may do, with decisions tiered by risk. **Detective**, recording what it did and flagging what looks wrong. **Corrective**, stopping and undoing. **Accountability**, naming who answers for each agent. **Assurance**, proving the other four still work.

Four of five delivers close to nothing, since risk exits through the open part. Detection is the easiest to stand up and the easiest to mistake for control.

Assurance is the part organizations discover late. Definitions, data models, and agent instructions describe a business changing weekly, so controls written once decay quietly. Anthropic's published account of its internal analytics agent measured accuracy falling from roughly 95 percent to 65 percent within a month before maintenance was treated as an engineering problem. Assurance means a maintained set of known questions with known answers per domain, results tracked over time, a threshold a domain clears before it goes live to its stakeholders, and changes bypassing governed definitions failing review rather than getting noted. Governance without assurance is a policy nobody has checked in a month.

**5. Operating model and talent.** Who is accountable, and how the work ships. Whether the analyst role has shifted from building visualizations toward modeling knowledge, whether every semantic model and deployed agent has one named owner, and whether analytics runs as a product with a lifecycle. Delivery discipline matters as much as ownership. Definitions, models, and agent instructions belong in one canonical, versioned source, kept together so a change to a model and a change to the documentation describing it ship as one unit, and synced outward so Slack, an IDE, and a dashboard return the same answer to the same question. Accountability has to exist before capability arrives, so this dimension is a leading indicator rather than a description of today.

**6. Adoption and decision culture.** Whether analytics reaches the people it was meant to serve, and whether they act on it. Calibration is what you want, meaning teams accept sound recommendations and reject flawed ones at the rate evidence justifies. Both failure directions are real. Reviewing everything and approving it anyway makes delegation a slower form of manual work. Accepting without examining removes the safeguard exactly where it was load-bearing.

**7. Value realization.** Whether analytics produces identifiable, measured business results. Progression runs from counting licenses and dashboard views, to defining outcomes, to quantifying impact, to measuring the results of agent-driven decisions. Agentic analytics closes a loop traditional BI rarely did: insight, recommendation, action, outcome, learning. Part 5 sets out what value each transition produces and how to size it.

---

## Part 3. How the assessment works

Score each dimension 1 to 6 against the stage descriptions in Part 4, scoped to one decision domain.

**Gate, do not average.** Your stage is the lowest score among the dimensions gating entry to that stage. Averaging seven scores hides the one constraint stopping you, which is the only thing the assessment exists to find.

| Entering stage | Gated by |
|---|---|
| 3 Understand | Data reach, semantic definitions in use, assurance in place, adoption breadth |
| 4 Recommend | Decision culture, outcomes defined and measured |
| 5 Act | Semantic trust, governance loop closed, action reversibility, named ownership |
| 6 Operate | Engineered corrective controls, containment limits, ontology, value attribution |

**Governance is evaluated by closure, not level.** All five parts must operate at the tier your target stage demands. Any open part caps you at the highest stage whose loop closes completely.

Assurance activates earlier than the rest of the loop. Corrective controls have nothing to stop until agents act, so they matter from stage 5. Assurance matters from stage 3, since an agent answering questions is already capable of being confidently wrong. A domain with no measured accuracy is not ready to be announced to the people who will rely on it.

**Require demonstration at the gates.** Deployment evidence is not maturity evidence. At a gate, ask for the test:

- Agent answers for your top metrics tie to the authoritative calculation, on live data, inside a stated tolerance
- Force a failure midway through a multi-step action, and nothing partial remains
- Execute a reversal on a reversible action, and show the recovery workflow for one that compensates
- Trigger a cascade and confirm it stops at the cap
- Pull 90 days of approval decisions and check whether rejections track real failure modes
- Show the eval results for this domain over the last quarter, and the threshold it cleared before launch
- Name a recent change to a definition or an agent instruction, and show the measured effect

That last one deserves attention. An approval rate above 95 percent with no pattern behind the rejections means your approvers are clicking. At stage 5, the approver is the corrective control, so an unexamined approval makes that control decorative.

**Capture the baseline before you remediate.** Every value figure in Part 5 needs a before number, and the before number stops being available once the work starts. Take the two or three measures you intend to claim against, record them, and date them. A transition proving new capability without a baseline produces no defensible value case.

**Record trajectory alongside the score.** Operating model, adoption, and value take quarters to move. A score set last quarter and a score frozen for two years call for different plans. Sustained decline matters more than absolute level.

---

## Part 4. Scoring reference

| Dimension | 1 Minimal | 2 Emerging | 3 Performing | 4 Optimizing | 5 Leading | 6 Autonomous |
|---|---|---|---|---|---|---|
| Data foundation | Siloed extracts | Some integration | One federated surface, lineage exists | Quality rules hold, sources certified | Transaction grain retained, permissions at source, freshness stated | Stewardship on call, schema contracts upstream |
| Semantic layer and ontology | Definitions per workbook | Documented, duplicated | Shared definitions for core metrics | Domain models in use, atomic grain exposed | Business-ratified, versioned, reconciled to authoritative calculations | Entity model and constraints span domains |
| Action and integration surface | Read only | Manual handoff | Insights delivered to work surfaces | Action initiated inside the workflow | Governed writes, actions classified reversible or compensating | Cascade and blast radius capped, actions idempotent |
| Governance and trust | Permissions only | Certified assets | Lineage, traceability, accuracy measured per domain | Policy defined for AI outputs, release thresholds enforced | Loop closed at approval tier, owner per agent, regressions detected | Engineered halt and rollback, exception review rhythm |
| Operating model and talent | Report factory | Self-service enablement | Some semantic modeling, definitions versioned | Knowledge architect role defined, one canonical source synced to all surfaces | Named owner per model and agent, in objectives | Analytics runs as a product, with deprecation |
| Adoption and decision culture | Analysts only | Broader business use | Data consulted before deciding | Teams act on unprompted insight | Approvers demonstrably examine | Teams trust policy and inspect outliers |
| Value realization | Licenses and usage | Adoption measured | Outcomes defined and attributed | Value tied to interventions | Agent-driven outcomes measured | Optimized against business results |

---

## Part 5. Value at each transition

Value realization gates the top of the curve. That alone does not help you plan, since it tells you what to prove at the end rather than what to expect from each step.

Each transition produces a different kind of value through a different mechanism. Name the mechanism and the business case writes itself. Skip it and the program gets funded on a generic efficiency argument, then judged against results it was never going to produce.

**Two forms of value.** Risk amelioration covers regulatory compliance, reputation and goodwill, employee satisfaction and turnover, and consistency of outcomes. Business performance covers cost reduction, revenue increase, and customer satisfaction. Consistency of outcomes is the bridge, reading as risk and paying into performance, since variance in decisions reaches margin and customer experience before it reaches an audit finding. Decision latency is a mechanism rather than a category, and every transition below moves it.

**How the value changes shape.** Stages 1 to 3 make the decisions you already make faster, cheaper, and consistent. Stages 3 to 5 increase the number of decisions made at all. Stages 5 to 6 remove the labor ceiling on decision volume. A cost-reduction case fits the first band and understates the second.

### 1 to 2. Find to Ask

**Mechanism.** The request queue disappears for any question the data already answers.

- Cost reduction. Analyst hours on rote pulls return to the organization. Most teams spend 40 to 60 percent of capacity on repeat requests needing no judgment.
- Employee satisfaction, two populations. Analysts stop being a report factory, the most common reason good analysts leave. Business users stop waiting days for a number.
- Revenue increase, indirectly, as redeployed analyst capacity moves to causal work, forecasting, and modeling.

**Handles.** Ad hoc request volume and the share needing no judgment. Analyst hours per request at loaded rate. Median days from question to answer. Analyst attrition and replacement cost.

This produces the same decisions sooner rather than better decisions. Consistency does not improve here and often worsens, since conversational access to ungoverned data spreads conflicting numbers faster.

### 2 to 3. Ask to Understand

**Mechanism.** One governed number, traceable, delivered where work happens.

- Consistency of outcomes. The same question returns the same answer to everyone, every time.
- Cost reduction, larger than most companies estimate. Count the hours spent reconciling conflicting numbers before every leadership meeting, board pack, and quarterly review. That labor is invisible because it is distributed.
- Regulatory compliance. One authoritative definition with lineage is the difference between answering an examiner in an hour and in three weeks. Restatements become rare.
- Reputation and goodwill, internally first. Leadership stops discounting analytics because two decks disagreed last quarter.
- Revenue increase, since decisions stop stalling while people argue about whose number is right.

**Handles.** Hours per reporting cycle spent reconciling figures across all functions. Restatements in the last four quarters. Time to answer a regulatory data request. Decisions delayed by disputed data, and the delay length. Close cycle length.

This is the most CFO-legible transition on the curve. The costs it removes are already being paid, in labor nobody line-items. It is also the transition most often skipped in favor of visible capability.

### 3 to 4. Understand to Recommend

**Mechanism.** Detection without a question. Coverage moves from what people thought to ask about to everything monitored.

First transition producing value from decisions nobody would otherwise have made.

- Cost reduction through earlier detection. Inventory written off, campaign spend wasted, contract leakage, and margin erosion all compound while undetected.
- Revenue increase through found opportunity. Nobody files a request for a pattern they do not know exists.
- Customer satisfaction. Issues surface before customers report them, turning an apology into a notification.
- Consistency of outcomes. Monitoring stops depending on which analyst is watching which metric this week.

**Handles.** Mean time to detect, before and after, on a defined problem class. Cost per day of delayed detection for two or three classes with known economics. Issues surfaced in the first quarter nobody had asked about, valued individually. Share of monitored metrics with someone actively watching them, usually far lower than leadership assumes.

Do not justify this transition on labor savings. Framed as efficiency it underdelivers against its own case while succeeding at something more valuable.

### 4 to 5. Recommend to Act

**Mechanism.** Execution coverage. People triage and act on the top slice. Agents act across the whole distribution.

Ask what share of flagged items gets acted on today. The answer is usually 5 to 20 percent, and the gap is a capacity limit rather than carelessness. The tail holds real value in aggregate and no single item justifies a person's time.

- Revenue increase and cost reduction from the tail. Thousands of small actions nobody had capacity to take.
- Consistency of outcomes, sharply. The same conditions produce the same action every time, rather than depending on who was on shift.
- Customer satisfaction. Response time moves from days to minutes on routine matters.
- Employee satisfaction. People stop executing decisions already made for them and move to exceptions needing judgment.

**Handles.** Share of surfaced recommendations acted on today, and why. Aggregate value of the unacted tail. Current time from insight to action. Variance in outcomes for the same decision type across people, shifts, or regions. Volume of routine executions per month and the hours they consume.

The value case here is net of the governance and containment work making it safe. That work is the cost of the value, not overhead.

### 5 to 6. Act to Operate

**Mechanism.** Removing the approval step removes the labor ceiling on decision volume and the latency floor on decision speed.

- Cost reduction, direct. A thousand approvals a day at two minutes each is a role and a half doing nothing but clicking.
- Revenue increase from decisions impossible at human latency. Dynamic pricing, real-time dispatch, and rebalancing inside a delivery window do not exist without autonomy.
- Consistency of outcomes, near-total for in-scope decisions.
- Customer satisfaction, where response time is the experience.
- Employee satisfaction, handled well. Supervising exceptions beats approving a queue. Handled poorly it reads as displacement.

**Handles.** Approval labor hours per month at loaded rate. Decisions per day capped by available approvers. Decisions the business would make at seconds rather than hours of latency, and their value. Cost per decision.

Risk changes character here rather than improving. Errors become rarer and more concentrated, so expected loss usually falls while worst-case single-incident loss usually rises. Present both, since a risk committee will ask.

### Where value moves backward

Four honest exceptions, and a value story claiming uniform improvement will not survive review.

Consistency dips at Stage 2, as conversational access spreads conflicting definitions faster than dashboards did. The fix is Stage 3, which argues against stopping at 2.

Reputation risk peaks across Stages 3 to 5. The first visible AI error costs more than its direct impact, because it sets the internal narrative about whether the capability works.

Employee satisfaction is not monotonic. Analysts gain when rote work leaves and lose when their role changes without a path. Operating model is the dimension protecting this, specifically whether the knowledge architect role exists before the old work disappears.

Regression destroys value faster than it was built. Trust is asymmetric, and recovering credibility after a visible wrong answer takes far longer than earning it did. Assurance protects realized value.

### Building the case for a transition

Three figures per transition.

**Value unlocked.** Take the mechanisms above, keep the two or three with economics the customer already tracks, and size them. Two defensible numbers beat seven estimated ones.

**Cost to gate.** The remediation clearing the gates for that transition.

**Attribution.** Some remediation serves several transitions. Definition adjudication delivers the Stage 3 consistency value and is a prerequisite for Stage 5. Charge it where the value first lands, then treat it as sunk. Loading full cost onto every transition it enables makes the whole curve look uneconomic.

Remediation cost is mostly one-time and organizational while value recurs, so payback improves with each year held rather than each stage added. And the transitions differ in payback shape. Stage 2 to 3 pays back from labor already being spent, which is fast and defensible. Stage 3 to 4 pays back from value not yet existing, which is larger and harder to underwrite. Fund them with different evidence standards.

---

## Part 6. Three common stalls

**Stalled below stage 5, on semantics.** A specialty insurer spent nine months moving 1,400 calculated fields out of workbooks into shared models. Adjusters ask questions in plain language and get answers. Then the tie-out failed on 6 of 11 core metrics, because claims operations, actuarial, and the commercial line each hold a defensible definition of "open claim" and none is authoritative. For twenty years the difference was a footnote an analyst reconciled by hand. The moment an agent acts, a claim excluded from the open population never reaches a queue, and nothing alerts. The fix took 14 to 18 weeks and no new technology: adjudicate the definitions the agent reads, name a business steward for each, stand up a monthly review, and run a nightly reconciliation job.

**Stalled below stage 6, on governance.** A logistics operator ran stage 5 for seven months with complete logging and a dashboard the operations director reviewed weekly. Dispatchers approved 1,100 recommendations a day and cleared 94 percent unchanged. The remaining 6 percent held five recurring failure modes nobody had examined, including reassignments to carriers without the required endorsement and dock appointments against facilities closed for a holiday. Seven months of visibility told them what happened and stopped nothing. The fix converts observed failures into enforced rules, caps cascade depth, builds circuit breakers and rollback, and removes approval one region and one action type at a time.

**Slipping backward, on assurance.** A software company launched a conversational analytics agent to 600 business users and measured 94 percent accuracy at launch on a set of validated questions. Nobody owned the reference material afterward. Six schema changes and two product renames later, accuracy sat in the mid sixties and nobody knew, because the answers still looked reasonable and the corrections happened quietly in Slack threads. The fix is unglamorous: keep the definitions and the documentation describing them in one place so they change together, rerun the validated question set on every change, and make a domain owner accountable for the number.

None of these companies needed a new platform. All three needed organizational work that took longer than the technology work before it.

---

## Part 7. From assessment to plan

The output is one register per decision domain.

| Domain | Target | Today | Binding constraint | Evidence gap | First move |
|---|---|---|---|---|---|
| Finance reporting | 5 Act | 4 Optimizing | Semantic trust | Definitions not ratified by business owners | Convene metric owners, name stewards |
| Reversible operational nudges | 6 Operate | 5 Leading | Governance corrective | No automatic halt or rollback | Build circuit breakers before removing approval |

No composite score. The register is the deliverable, and it drives the conversation that matters: where you are, what is blocking you, what to do about it, what stage you are aiming for, and what business outcome that produces.

**Sequencing that holds across engagements**

- Action capability never runs ahead of governance
- Data reach comes before semantic work, since you cannot model meaning on data you cannot trust
- Definition consensus starts immediately, since nothing technical blocks it and it takes the longest
- Ontology follows domain semantics, scoped to the domains agents actually cross
- Governance leads the curve by one stage, and comes from operating the stage below long enough to see how agents fail in your business
- Assurance starts at stage 3 and never stops, since an unmaintained knowledge layer degrades in weeks
- Roles, ownership, and culture gate the top of the curve and take quarters to move, so start them at the bottom

---

## Part 8. What this is for

Every stage above 3 asks you to trust something more consequential than the last, and trust is expensive to build and cheap to lose. That is why the gates are evidence rather than deployment, and why value realization gates the top of the curve alongside governance and semantics.

Each transition also pays differently, which Part 5 sets out. Match the business case to the transition. A stage 4 program funded on analyst savings will underdeliver against its own case while succeeding at something more valuable.

One caution about where to invest. Models improve quickly, and some of what looks like required infrastructure today exists to compensate for a current model limitation. The dimensions in this model are mostly organizational, covering definitions, ownership, control, and value, and those hold their worth regardless of which model you run. The parts most exposed to model progress are the mechanics of how context reaches an agent. Weight your investment toward the work that survives a model upgrade.

An organization is not more mature because its agents do more. It is more mature when more of its decisions are made well, faster, with results it measures. Stage 6 with no measured outcome is a liability. Stage 4 with quantified value and a clear path forward is a success.

Set your target per domain. Prove each gate. Measure what it returns.
