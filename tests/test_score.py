"""M6 acceptance (build brief section 5):

  - a target stage of 5 on the median fixture yields readiness 2 with
    `semantic.singularity` as the binding constraint
  - removing the target emits facet scores and no rollup
  - an interview response claiming a stronger score than the scan measured
    raises `INT-01` and does not overwrite the scan value
  - a test fails if `findings.json` gains a top-level score field

Plus focused unit tests for the two pieces the median rollup does not exercise:
the flag-cap syntax and governance loop closure. Both are built for the live
path and must be provable directly, not only through the fixture.
"""

import json
import os

import pytest

from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.group import assign_groups
from estate_scan.derive.rank import rank_groups
from estate_scan.derive.resolve import resolve_all
from estate_scan.extract.runner import ExtractRunner
from estate_scan.flags.engine import evaluate_flags
from estate_scan.score import score
from estate_scan.score.facets import score_capped, score_threshold
from estate_scan.score.rollup import (domain_rollup, governance_binding,
                                      governance_score)
from estate_scan.store import Store

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _scored_store(profile="median"):
    """A store carried through the full deterministic pipeline -- the state the
    scorer reads: resolved formulas, groups, ranks, and flags."""
    estate = os.path.join(FIXTURES, profile, "estate.json")
    client = FixtureClient.from_path(estate)
    config = client.run_config()
    store = Store.open(":memory:")
    ExtractRunner(client, store, "r").run()
    resolve_all(store, "r")
    assign_groups(store, "r", core_metrics=config.get("core_metrics") or None)
    rank_groups(store, "r")
    evaluate_flags(store, "r")
    return store, config


def _facet_scores(findings):
    return {f["id"]: f for f in findings["facets"]}


# -- acceptance: target stage, rollup, binding constraint --------------------

def test_target_five_yields_readiness_two_with_singularity_binding():
    store, config = _scored_store("median")
    findings = score(store, "r", config=config)  # median declares target 5

    facets = _facet_scores(findings)
    # R4 scores the semantic, adoption, and data facets from the scan.
    assert facets["semantic.singularity"]["score"] == 2
    assert facets["semantic.singularity"]["confidence"] == "observed"
    assert facets["semantic.describability"]["score"] == 3
    assert facets["semantic.exposure_shape"]["score"] == 2
    assert facets["adoption.reach"]["score"] == 4
    # data.entitlement_at_source: base 6 capped to 2 because SEC-01 fires.
    assert facets["data.entitlement_at_source"]["score"] == 2
    assert facets["data.entitlement_at_source"]["confidence"] == "observed"

    assert len(findings["domains"]) == 1
    dom = findings["domains"][0]
    assert dom["id"] == "revenue_ops"
    assert dom["target_stage"] == 5
    assert dom["readiness"] == 2
    assert dom["gap"] == 3
    # Data now gates stage 5 too and ties semantic at the minimum, so both are
    # named as binding constraints.
    assert dom["binding_constraints"] == ["data.entitlement_at_source",
                                          "semantic.singularity"]
    assert dom["dimension_scores"] == {"data": 2, "semantic": 2}
    assert dom["confidence"] == "observed"


def test_removing_the_target_emits_facets_and_no_rollup():
    store, config = _scored_store("median")
    no_target = {"core_metrics": config.get("core_metrics", []), "domains": []}
    findings = score(store, "r", config=no_target)

    assert findings["domains"] == []
    facets = _facet_scores(findings)
    assert facets["semantic.singularity"]["score"] == 2
    assert facets["adoption.reach"]["score"] == 4


# -- coverage honesty: unmeasured usage is not low reach (plan invariant 7) --

def test_reach_drops_out_when_usage_events_not_ok():
    """adoption.reach derives from content_activation over the usage table. If
    usage_events did not measure (e.g. REST 501 on the live path), that table is
    empty and a score would read as "hardly anyone uses this" -- a false low.
    The `requires_coverage` guard must drop the facet so its dimension reports
    as unscored, not clean. The fixtures record usage_events `ok`, so the guard
    only bites when coverage is flipped."""
    store, config = _scored_store("median")

    # Baseline: usage_events is `ok` on the fixture, so reach scores.
    assert store.coverage_status("r", "usage_events") == "ok"
    assert "adoption.reach" in _facet_scores(score(store, "r", config=config))

    # Flip the coverage row to a live-path failure and re-score.
    store.record_coverage("r", "usage_events", "failed", "REST status 501")
    facets = _facet_scores(score(store, "r", config=config))
    assert "adoption.reach" not in facets, \
        "unmeasured usage must not produce an observed reach score"


# -- acceptance: interview never overwrites the scan (INT-01) ----------------

def test_interview_claiming_stronger_raises_int01_without_overwriting():
    store, config = _scored_store("median")
    # Scan measured singularity at 2; the interview claims 5.
    store.save_interview_response(
        "r", "semantic.singularity", 5, "leadership believes it is standard",
        "analytics_leader", "", "2026-01-01T00:00:00Z", "specialist",
        "reported")
    store.commit()

    findings = score(store, "r", config=config, now="2026-01-01T00:00:00Z")

    facets = _facet_scores(findings)
    # Scan wins: the value stays 2 and observed, not the claimed 5.
    assert facets["semantic.singularity"]["score"] == 2
    assert facets["semantic.singularity"]["confidence"] == "observed"

    int01 = [r for r in store.flags("r") if r["flag_id"] == "INT-01"]
    assert len(int01) == 1
    ev = json.loads(int01[0]["evidence_json"])
    assert ev["scan_score"] == 2
    assert ev["interview_score"] == 5
    assert ev["facet"] == "semantic.singularity"


def test_interview_scores_a_facet_the_scan_cannot_see():
    store, config = _scored_store("median")
    # semantic.consensus is interview-only (no scan measure).
    store.save_interview_response(
        "r", "semantic.consensus", 2, "tie-out fails against finance close",
        "finance_lead", "", "2026-01-01T00:00:00Z", "specialist", "reported")
    store.commit()

    findings = score(store, "r", config=config, now="2026-01-01T00:00:00Z")
    facets = _facet_scores(findings)
    assert facets["semantic.consensus"]["score"] == 2
    assert facets["semantic.consensus"]["evidence"] == "reported"
    assert facets["semantic.consensus"]["confidence"] == "reported"


# -- acceptance: no composite score, ever ------------------------------------

def test_findings_has_no_top_level_score_field():
    store, config = _scored_store("median")
    findings = score(store, "r", config=config)

    # The whole point of the assessment is the binding constraint, not an
    # average. A top-level score anywhere is a regression.
    assert set(findings.keys()) == {"facets", "domains"}
    assert "score" not in findings

    # And the same must hold for what was persisted for the report step.
    persisted = json.loads(store.score_output("r")["findings_json"])
    assert set(persisted.keys()) == {"facets", "domains"}
    assert "score" not in persisted


# -- unit: flag-cap syntax ---------------------------------------------------

def test_score_capped_pulls_score_down_when_flag_fires():
    caps = [{"flag": "SEC-01", "when": "> 0", "max_score": 2}]
    capped, deriv = score_capped(6, caps, {"SEC-01": 22})
    assert capped == 2
    assert "SEC-01" in deriv


def test_score_capped_leaves_base_when_flag_absent():
    caps = [{"flag": "SEC-01", "when": "> 0", "max_score": 2}]
    capped, _ = score_capped(6, caps, {})
    assert capped == 6


def test_score_capped_takes_the_lowest_applicable_cap():
    caps = [{"flag": "A", "when": "> 0", "max_score": 4},
            {"flag": "B", "when": "> 0", "max_score": 2}]
    capped, _ = score_capped(6, caps, {"A": 1, "B": 1})
    assert capped == 2


# -- unit: band grammar ------------------------------------------------------

def test_band_grammar_covers_cmp_range_and_boolean_gate():
    bands = {"2": "< 0.4", "3": "0.4 - 0.7", "4": "> 0.7",
             "5": "> 0.7 and ratified == true"}
    # comparison and range
    assert score_threshold(bands, 0.2, {})[0] == 2
    assert score_threshold(bands, 0.5, {})[0] == 3
    # a boolean input the scan cannot observe reads false: caps below band 5
    assert score_threshold(bands, 0.9, {})[0] == 4
    # supply the interview-derived input and band 5 opens
    assert score_threshold(bands, 0.9, {"ratified": True})[0] == 5


def test_band_grammar_floors_to_one_when_no_band_holds():
    bands = {"3": "> 0.7"}
    assert score_threshold(bands, 0.1, {})[0] == 1


def test_unrecognised_band_clause_raises():
    with pytest.raises(ValueError):
        score_threshold({"2": "roughly 0.5"}, 0.5, {})


# -- unit: governance loop closure -------------------------------------------

# Arc activation from the framework (build spec / rules.yaml governance_arcs):
# preventive & accountability from stage 2, detective & assurance from 3,
# corrective from 5.
ARCS = {
    "preventive": {"activates_at": 2},
    "accountability": {"activates_at": 2},
    "detective": {"activates_at": 3},
    "assurance": {"activates_at": 3},
    "corrective": {"activates_at": 5},
}


def test_governance_is_unscored_when_no_arc_is_measured():
    # The prototype case: no governance interview responses -> None, so the
    # dimension reads as unscored rather than as a closed loop.
    assert governance_score({}, ARCS, 5) is None


def test_governance_closes_at_highest_complete_stage():
    # Every active arc reaches 5: the loop closes at 5.
    full = {"preventive": 5, "accountability": 5, "detective": 5,
            "assurance": 5, "corrective": 5}
    assert governance_score(full, ARCS, 5) == 5


def test_governance_capped_by_the_weakest_active_arc():
    # corrective (active only at 5) lags at 3; stage 5's loop cannot close, but
    # every arc active at 4 reaches 4, so governance scores 4.
    scores = {"preventive": 5, "accountability": 5, "detective": 5,
              "assurance": 5, "corrective": 3}
    assert governance_score(scores, ARCS, 5) == 4


def test_governance_unscored_when_an_active_arc_has_no_reading():
    # Coverage-first-class (plan invariant 7): some arcs are measured, but an arc
    # ACTIVE at the target has no reading at all. Treating its silence as a zero
    # would manufacture a low governance floor from absence -- a false negative --
    # so the loop reports unscored instead. This is the guard that keeps the two
    # observed arcs (accountability, assurance) from scoring governance on their
    # own while preventive/detective/corrective stay interview-only.
    observed_only = {"accountability": 6, "assurance": 4}  # the scan-readable pair
    assert governance_score(observed_only, ARCS, 5) is None
    # Even aiming only at stage 2, preventive is active and unread -> unscored.
    assert governance_score({"accountability": 6}, ARCS, 2) is None


def test_governance_ignores_arcs_that_only_activate_above_the_target():
    # An arc that activates ABOVE the target does not constrain a domain aiming
    # lower, so its absence does not block a score. corrective activates at 5;
    # a domain aiming at 3 with every arc active at 3 reaching 3 closes at 3,
    # even though corrective was never read.
    aiming_three = {"preventive": 3, "accountability": 3, "detective": 3,
                    "assurance": 3}  # corrective unread, irrelevant below stage 5
    assert governance_score(aiming_three, ARCS, 3) == 3


# -- unit: governance binding constraint (the R4 fix) ------------------------

def test_governance_binding_names_the_arc_that_holds_the_loop():
    # Companion to the score: corrective lags at 2, so the loop closes at 4 and
    # the arc that stops it closing at 5 is corrective.
    scores = {"preventive": 5, "accountability": 5, "detective": 5,
              "assurance": 5, "corrective": 2}
    gov = governance_score(scores, ARCS, 5)
    assert gov == 4
    assert governance_binding(scores, ARCS, gov) == ["governance.corrective"]


def test_governance_binding_empty_when_unscored_or_at_ceiling():
    # No arc measured -> no binding (governance is unscored, not bound).
    assert governance_binding({}, ARCS, None) == []
    # Loop already closed at the ceiling -> nothing above it can fail.
    full = {"preventive": 6, "accountability": 6, "detective": 6,
            "assurance": 6, "corrective": 6}
    assert governance_binding(full, ARCS, 6) == []


def test_domain_rollup_names_the_failing_governance_arc():
    # The confirmed defect: when governance is the sole minimum the register
    # used to name no constraint at all (binding_by_dim skipped governance) and
    # report "observed" confidence -- a low readiness with no cause. The arc's
    # facet record is interview-derived (evidence "reported"), so the domain
    # must read "reported".
    facets = [
        {"id": "semantic.singularity", "dimension": "semantic", "score": 5,
         "evidence": "observed", "gates": [5]},
        {"id": "governance.corrective", "dimension": "governance", "score": 2,
         "evidence": "reported", "gates": []},
    ]
    dim_scores = {"semantic": {"score": 5,
                               "gating_facets": ["semantic.singularity"]}}
    scores = {"preventive": 5, "accountability": 5, "detective": 5,
              "assurance": 5, "corrective": 2}
    gov = governance_score(scores, ARCS, 5)            # loop closes at 4
    gov_binding = governance_binding(scores, ARCS, gov)
    dom = domain_rollup({"id": "d", "target_stage": 5}, facets, dim_scores,
                        gov, gov_binding)

    assert dom["readiness"] == 4
    assert dom["dimension_scores"] == {"governance": 4, "semantic": 5}
    assert dom["binding_constraints"] == ["governance.corrective"]
    assert dom["confidence"] == "reported"


def test_interview_arc_scores_make_governance_the_binding_constraint():
    # End to end through the scorer: a single governance arc placed below its
    # stage-2 tier drops the governance loop to 1 -- below the scan's semantic
    # floor of 2 -- so governance becomes the binding dimension and names its
    # arc, with confidence "reported" because the floor is interview-derived.
    store, config = _scored_store("median")
    arcs = {"preventive": 1, "accountability": 5, "detective": 5,
            "assurance": 5, "corrective": 5}
    for arc, sc in arcs.items():
        store.save_interview_response(
            "r", "governance.%s" % arc, sc, "arc %s" % arc, "governance_lead",
            "", "2026-01-01T00:00:00Z", "specialist", "reported")
    store.commit()

    findings = score(store, "r", config=config, now="2026-01-01T00:00:00Z")
    dom = findings["domains"][0]
    assert dom["readiness"] == 1
    assert dom["dimension_scores"].get("governance") == 1
    assert dom["binding_constraints"] == ["governance.preventive"]
    assert dom["confidence"] == "reported"


# -- observed governance arcs: the two arcs the scan can read directly --------

def test_observed_governance_arcs_are_scored_from_the_scan():
    # accountability (share of sources with a named owner) and assurance
    # (certified share) are the two governance arcs the scan reads directly.
    # They enter the facet list as OBSERVED governance facets, banded from
    # rules.yaml exactly like a threshold facet -- no interview required.
    store, config = _scored_store("median")
    facets = _facet_scores(score(store, "r", config=config))

    acc = facets["governance.accountability"]
    assert acc["dimension"] == "governance"
    assert acc["evidence"] == "observed"
    assert acc["confidence"] == "observed"
    # Every median source carries an owner -> ownership coverage 1.0 -> the
    # top band ("== 1") -> tier 6. This reads the fixture's ground truth; the
    # bands are not tuned to hit it (build brief 7).
    assert acc["score"] == 6
    assert acc["inputs"]["ownership_coverage"] == 1.0

    asr = facets["governance.assurance"]
    assert asr["dimension"] == "governance"
    assert asr["evidence"] == "observed"
    # Certified share sits below the lowest band on this fixture, so the arc
    # scores its floor (tier 1) -- a real low reading, not an absence.
    assert asr["score"] == 1
    assert "certification_coverage" in asr["inputs"]


def test_observed_governance_arcs_do_not_score_governance_on_their_own():
    # The two observed arcs are present, but preventive/detective/corrective are
    # interview-only and unread on a scan-only run. The completeness gate must
    # therefore leave governance UNSCORED -- it is absent from the domain's
    # dimension_scores, never a false floor from the two arcs it could read.
    store, config = _scored_store("median")
    dom = score(store, "r", config=config)["domains"][0]
    assert "governance" not in dom["dimension_scores"]
    assert dom["dimension_scores"] == {"data": 2, "semantic": 2}


def test_observed_governance_arcs_drop_when_datasources_coverage_not_ok():
    # The observed arcs are coverage-gated on `datasources` (requires_coverage).
    # If that feed did not measure, an ownership/certification share computed
    # over an empty or partial table would be a false reading, so the arcs must
    # drop out entirely rather than score a floor.
    store, config = _scored_store("median")
    base = _facet_scores(score(store, "r", config=config))
    assert "governance.accountability" in base
    assert "governance.assurance" in base

    # Flip the datasources coverage to a live-path failure and re-score.
    store.record_coverage("r", "datasources", "failed", "metadata query 501")
    facets = _facet_scores(score(store, "r", config=config))
    assert "governance.accountability" not in facets
    assert "governance.assurance" not in facets


def test_interview_supplies_an_arc_the_scan_cannot_observe():
    # preventive posture is not settleable from a scan, so it stays absent from
    # the observed arcs and is scored from the interview instead -- marked
    # reported, like any interview-only facet. This is how the three
    # non-observable arcs feed the loop.
    store, config = _scored_store("median")
    store.save_interview_response(
        "r", "governance.preventive", 4, "grants reviewed quarterly",
        "governance_lead", "", "2026-01-01T00:00:00Z", "specialist", "reported")
    store.commit()

    facets = _facet_scores(score(store, "r", config=config,
                                 now="2026-01-01T00:00:00Z"))
    prev = facets["governance.preventive"]
    assert prev["score"] == 4
    assert prev["evidence"] == "reported"
    assert prev["confidence"] == "reported"


# -- the four-subcommand CLI shape -------------------------------------------

def test_cli_pipeline_scan_interview_score(tmp_path):
    from estate_scan import cli

    out = str(tmp_path)
    estate = os.path.join(FIXTURES, "median", "estate.json")

    assert cli.main(["scan", "--fixture", estate, "--out", out]) == 0
    assert os.path.exists(os.path.join(out, "estate.db"))
    assert os.path.exists(os.path.join(out, "run.log"))

    # score resolves the run and reads the persisted config (target 5)
    assert cli.main(["score", "--out", out]) == 0
    store = Store.open(os.path.join(out, "estate.db"))
    findings = json.loads(store.score_output(store.latest_run_id())
                          ["findings_json"])
    store.close()
    dom = findings["domains"][0]
    assert dom["readiness"] == 2
    assert dom["binding_constraints"] == ["data.entitlement_at_source",
                                          "semantic.singularity"]

    # --no-rollup drops the domain rollup
    assert cli.main(["score", "--out", out, "--no-rollup"]) == 0
    store = Store.open(os.path.join(out, "estate.db"))
    findings = json.loads(store.score_output(store.latest_run_id())
                          ["findings_json"])
    store.close()
    assert findings["domains"] == []
