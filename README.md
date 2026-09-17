# Tableau Estate Scan

Read-only scan of a Tableau Cloud/Server estate that produces an agentic-analytics readiness assessment: seven dimensions scored against a per-domain target stage, the binding constraint named rather than a composite score, coverage first-class, and a self-contained offline report.

The tool is the `estate_scan/` Python package. The numbered specification documents below define the framework it scores against, the methodology, and the decisions behind the build.

## Getting the code

Requires **Python 3.9 or newer** (developed and tested through 3.14). The only runtime dependencies are `httpx`, `jinja2`, `openpyxl`, and `pyyaml`; SQLite is used through the standard library.

```bash
git clone https://github.com/khodgkins-ship-it/tab-agentic-readiness-scan.git
cd tab-agentic-readiness-scan
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .                   # installs deps and the `estate_scan` command
```

That's everything the offline path needs — no Tableau access, no credentials. To run the test suite (all offline, no network):

```bash
pip install -e ".[dev]"
python -m pytest -q
```

Every command below is also available as `python -m estate_scan …` if you prefer not to rely on the installed console script.

## Running an assessment

The pipeline is four stages sharing one SQLite store under the output directory: `scan → interview → score → report`. `scan` takes its data from either a recorded fixture (offline) or a live Tableau site; the later stages read whatever the most recent `scan` left in the store, so a single run needs no run-id plumbing.

### Try it offline (no Tableau access)

Three bundled fixtures — `small`, `median`, `hostile` — replay a recorded estate with no network calls:

```bash
estate_scan scan   --fixture tests/fixtures/median --out out/demo
estate_scan score  --out out/demo
estate_scan report --out out/demo
```

`report` writes five artifacts into `out/demo/`: `findings.json`, `report.md`, `variants.xlsx`, and two self-contained HTML builds. Open `report.presentation.html` in a browser (it works straight from `file://`, with no network) — it is the redacted, shareable build. `report.working.html` carries full detail (resolved formulas, owner names) and is the one that stays with the analytics team. Add `--framing light` to render the same findings with no stage or score language, for accounts that reject a maturity ladder.

The `interview` step is optional for a fixture run; `score` runs without it.

### Scan a real Tableau site

The live path is read-only, enforced in code, and needs a **read-only Personal Access Token**. It is deliberately two-step so pointing the tool at a config can never silently connect.

1. Copy the config template and fill in your site (the committed template is the only `live-config.*` file tracked; your filled-in copy stays local and gitignored):

   ```bash
   cp live-config.example.yaml live-config.yaml
   # edit: host, site_content_url, deployment_type (cloud|server), pat_name
   ```

2. Provide the PAT **secret** through the environment — never in the config file:

   ```bash
   export ESTATE_SCAN_PAT_NAME="<your PAT name>"
   export ESTATE_SCAN_PAT_SECRET="<your PAT secret>"
   ```

   (An OS keychain entry via the optional `keyring` package works too.)

3. Validate the config without connecting anywhere:

   ```bash
   estate_scan scan --config live-config.yaml --out out/live
   ```

4. Connect and scan — the explicit `--live` opt-in is what actually reaches the site:

   ```bash
   estate_scan scan --config live-config.yaml --live --out out/live
   ```

   On Tableau Cloud there is no REST endpoint for per-workbook view counts, so the scan sources adoption from the Tableau-managed **Admin Insights** published data source, read through the read-only VizQL Data Service as a grouped aggregate (one row per workbook: its view count and last-viewed date over a trailing window). This is automatic when the site has the service enabled — no extra step. Because Tableau localises and revises the Admin Insights schema, **confirm the field captions on your first live run**: if they don't resolve, usage is recorded as *unmeasured* with a reason (never guessed), and you set the right names under the optional `admin_insights:` block in the config and re-run. A site without the VizQL Data Service simply reports usage as unmeasured.

5. Capture the specialist judgments no API can see (declared target stage, governance posture) in a YAML responses file — see `02-assessment-methodology.md` for the interview protocol — then load them, score, and emit the report:

   ```bash
   estate_scan interview --out out/live --file interview-responses.yaml
   estate_scan score      --out out/live
   estate_scan report     --out out/live
   ```

Three more subcommands support the live workflow: `resolve` (execute read-only VizQL Data Service queries to test material disagreement between metric variants — a full-mode step run with the analyst present), `smoke` (a guarded read-only connectivity self-test), and `calibrate` (emit threshold distributions from a run). Run `estate_scan <command> --help` for the options on each.

**Security notes.** Read-only is enforced structurally by three in-code gates, so the live client cannot issue a mutation. The PAT secret is only ever read from the environment or the OS keychain — putting a secret in the config file is a hard error (the CLI scans the config and aborts before any client is built, naming the offending key but never the value). The tool talks only to your own Tableau host, and the offline pass makes no external calls. Run the credential-bearing commands (`--live`, `smoke`, `resolve --live`) yourself in your own terminal.

## Generating a narrative report or deck

The tool emits findings; it does not write prose and it makes no model calls. To
turn an assessment into a written readiness report or an executive presentation,
hand the artifacts to an AI **of your own choosing** (Claude or otherwise),
together with the instruction skill in [`skills/readiness-narrative/`](skills/readiness-narrative/).

The tool never egresses anything — you do, on your own account, entirely separate
from this build. So the choice of what to share, and with which model, is yours:

1. Run the pipeline (`scan → score → report`) to produce `out/`.
2. Share with your AI: `out/report.presentation.html` (the redacted, shareable
   build) or `out/findings.json`, plus `skills/readiness-narrative/SKILL.md`.
   Optionally add `01-maturity-framework-reference.md` and
   `02-assessment-methodology.md` for depth.
3. Ask for a narrative report, a presentation, or improvement recommendations.

Prefer the **presentation** build for any hosted/third-party model — it carries
no formulas or owner names. Share the **working** build only with a private or
local model you trust to see business logic and names. The skill (`SKILL.md`)
carries the full faithfulness contract it applies: no composite score,
coverage-first honesty, per-domain readiness named by its binding constraint, and
every figure grounded in the scan data.

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
