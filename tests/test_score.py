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
from estate_scan.score.rollup import governance_score
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
    # The prototype scores the semantic and adoption facets from the scan.
    assert facets["semantic.singularity"]["score"] == 2
    assert facets["semantic.singularity"]["confidence"] == "observed"
    assert facets["semantic.describability"]["score"] == 3
    assert facets["semantic.exposure_shape"]["score"] == 2
    assert facets["adoption.reach"]["score"] == 4

    assert len(findings["domains"]) == 1
    dom = findings["domains"][0]
    assert dom["id"] == "revenue_ops"
    assert dom["target_stage"] == 5
    assert dom["readiness"] == 2
    assert dom["gap"] == 3
    assert dom["binding_constraints"] == ["semantic.singularity"]
    assert dom["dimension_scores"] == {"semantic": 2}
    assert dom["confidence"] == "observed"


def test_removing_the_target_emits_facets_and_no_rollup():
    store, config = _scored_store("median")
    no_target = {"core_metrics": config.get("core_metrics", []), "domains": []}
    findings = score(store, "r", config=no_target)

    assert findings["domains"] == []
    facets = _facet_scores(findings)
    assert facets["semantic.singularity"]["score"] == 2
    assert facets["adoption.reach"]["score"] == 4


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
    assert dom["binding_constraints"] == ["semantic.singularity"]

    # --no-rollup drops the domain rollup
    assert cli.main(["score", "--out", out, "--no-rollup"]) == 0
    store = Store.open(os.path.join(out, "estate.db"))
    findings = json.loads(store.score_output(store.latest_run_id())
                          ["findings_json"])
    store.close()
    assert findings["domains"] == []
