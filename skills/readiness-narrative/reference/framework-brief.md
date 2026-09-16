# Framework brief

A condensed, self-contained summary of the Agentic Analytics Maturity and
Readiness Model — enough to reason about recommendations without the full
`01-maturity-framework-reference.md`. If the client shares the full document,
prefer it for depth.

## Four questions, kept separate

The model answers four questions and never collapses them into one number:

- **Maturity** — how much of the path from data to action is delegated to agents today.
- **Readiness** — what stands between the organization and the stage it intends to reach.
- **Trajectory** — progressing, holding, or slipping (needs two runs; a single scan cannot answer it).
- **Value** — whether any of it produces measured business results.

Technology enables maturity; buying a capability does not confer it. Every stage
requires **evidence, not deployment**.

## The six stages

| Stage | Name | Verb | In one line |
|---|---|---|---|
| 1 | Minimal | Find | Dashboards and reports; people find and interpret on their own. |
| 2 | Emerging | Ask | People ask questions in plain language over governed data. |
| 3 | Performing | Understand | The system understands business context, not just the question; answers are governed and accuracy is measured. |
| 4 | Optimizing | Recommend | Agents monitor what matters and surface findings unprompted, tied to action. |
| 5 | Leading | Act | Agents act inside guardrails; a person approves each action; actions are reversible or recoverable. |
| 6 | Autonomous | Operate | Agents act under policy-as-code; people supervise exceptions; automatic halt/rollback exists. |

**Higher is not automatically better.** Stage 6 suits reversible, high-volume,
low-consequence decisions. Stage 5 is often the right *permanent* home for
regulated or expensive-to-undo decisions. Target is set **per decision domain**,
not enterprise-wide. Recommend toward each domain's declared target, not toward 6.

## The seven dimensions

Your stage is the *outcome*; these seven dimensions *produce* it.

1. **Data foundation** — do agents reach data that is correctly shaped, accurate, traceable, current. Reach, fidelity, liveness. Liveness fails silently.
2. **Semantic layer and ontology** — the semantic layer defines what numbers mean (carries you to stage 5); the ontology defines how the business is put together (load-bearing at stage 6).
3. **Action and integration surface** — reach (insights/actions arrive where work happens) and containment (actions complete or unwind cleanly, blast radius capped).
4. **Governance and trust** — a control loop, not a ladder (see below).
5. **Operating model and talent** — who is accountable and how work ships; one named owner per model/agent; one canonical versioned source. A leading indicator.
6. **Adoption and decision culture** — whether analytics reaches its people and they act on it, accepting sound recommendations and rejecting flawed ones at a calibrated rate.
7. **Value realization** — whether analytics produces identifiable, measured business results, from counting views up to measuring agent-driven decision outcomes.

## Gate, don't average

A domain's stage is the **lowest score among the dimensions that gate entry to
that stage.** Averaging hides the one constraint stopping you — the only thing
the assessment exists to find.

| Entering stage | Gated by |
|---|---|
| 3 Understand | Data reach, semantic definitions in use, assurance in place, adoption breadth |
| 4 Recommend | Decision culture, outcomes defined and measured |
| 5 Act | Semantic trust, governance loop closed, action reversibility, named ownership |
| 6 Operate | Engineered corrective controls, containment limits, ontology, value attribution |

## Governance by closure, not level

Governance has five parts, **all required**: **preventive** (what an agent may
do), **detective** (record and flag), **corrective** (stop and undo),
**accountability** (who answers for each agent), **assurance** (proof the other
four still work). Four of five delivers almost nothing — risk exits through the
open part. An open part caps you at the highest stage whose loop closes
completely.

- **Assurance** matters from **stage 3** (an agent answering questions can be
  confidently wrong). It means maintained known-question/known-answer sets per
  domain, tracked over time, with a threshold cleared before launch.
- **Corrective** controls matter from **stage 5** (nothing to stop until agents act).

## The two expensive transitions — flag these

- **Stage 4 → 5.** Below it a bad metric definition yields a wrong chart an
  analyst catches; above it the same definition issues a wrong *action* with
  nobody in the path.
- **Stage 5 → 6.** Human approval is the brake; removing the approver means
  building a software replacement (corrective controls) *first*. Most programs
  that get hurt get hurt here.

Whenever a domain's target crosses one of these, call it out as a
disproportionately costly and risky step.

## Demonstration tests (evidence, not deployment)

Recommendations should be framed as passing the behavioral test at a gate, not as
buying or deploying a product:

- Agent answers for top metrics tie to the authoritative calculation, on live
  data, within a stated tolerance.
- Force a failure midway through a multi-step action — nothing partial remains.
- Execute a reversal on a reversible action; show the recovery workflow for a
  compensating one.
- Trigger a cascade and confirm it stops at the cap.
- Pull 90 days of approval decisions; check that rejections track real failure
  modes (a >95% approval rate with no pattern means the approvers are clicking).
- Show this domain's eval results over the last quarter and the threshold it
  cleared before launch.
- Name a recent change to a definition or agent instruction and show its measured
  effect.

## Capture the baseline before remediating

Every value claim needs a *before* number, and that number disappears once the
work starts. Recommend the client record the two or three measures they intend to
claim against, and date them, **before** acting on any recommendation.
