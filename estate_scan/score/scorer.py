"""Facet scoring and rollup entry point (build spec section 9).

Consumes flags, interview responses, the facet catalog, and the declared target
stage per domain. Produces a per-domain readiness register with the binding
constraint named. Emits NO composite score -- `findings` carries `facets` and
`domains` only, and a test fails if a top-level score field ever appears.

Scoring interaction with the interview (section 10.3): the scan always wins.
Where an interview response claims a facet is STRONGER than the scan measured,
INT-01 is raised (informational, both values recorded) and the scan value is
kept. A facet the scan cannot measure is scored from the interview instead,
marked `reported`.
"""

import datetime
import json
from typing import Dict, List, Optional

from estate_scan.flags.engine import load_rules
from estate_scan.score.facets import score_facet
from estate_scan.score.rollup import (dimension_rollup, domain_rollup,
                                      governance_score)

# facet-id prefix -> framework dimension, for interview-only facets not in the
# scored catalog.
_DIM_PREFIX = {
    "data": "data", "semantic": "semantic", "action": "action_surface",
    "governance": "governance", "operating": "operating_model",
    "adoption": "adoption", "value": "value",
}


def _dim_from(facet_id):
    # type: (str) -> str
    return _DIM_PREFIX.get(facet_id.split(".", 1)[0], facet_id.split(".", 1)[0])


def score(store, run_id, config=None, rules=None, rules_path=None, now=None):
    # type: (object, str, Optional[dict], Optional[dict], Optional[str], Optional[str]) -> dict
    rules = rules if rules is not None else load_rules(rules_path)
    facets_def = rules.get("facets", {})
    arcs_def = rules.get("governance_arcs", {})
    config = config or {}
    now = now or (datetime.datetime.utcnow().isoformat() + "Z")

    # Band inputs the scan cannot observe (duplicates_deprecated, ratified,
    # estate_wide) stay empty here, so scan-only runs cap at the observable
    # band. Interview capture could supply them later.
    inputs = {}  # type: Dict[str, object]

    # 1. scan-derived facets (the prototype scores semantic + adoption) --------
    facets_out = {}  # type: Dict[str, dict]
    for fid, fdef in facets_def.items():
        if not fdef.get("scored"):
            continue
        rec = score_facet(fid, fdef, store, run_id, inputs)
        if rec is not None:
            rec["confidence"] = "observed"
            facets_out[fid] = rec

    # 2. interview application -------------------------------------------------
    store.clear_flag(run_id, "INT-01")
    by_facet = {}  # type: Dict[str, list]
    for r in store.interview_responses(run_id):
        by_facet.setdefault(r["facet_id"], []).append(r)

    for fid, responses in by_facet.items():
        if fid in facets_out:
            # Scan measured it: scan wins. A response claiming stronger than the
            # scan is a finding, not an override.
            scan_score = facets_out[fid]["score"]
            for r in responses:
                if r["score"] is not None and r["score"] > scan_score:
                    _raise_int01(store, run_id, fid, scan_score, r, now)
        else:
            # Scan cannot see it: score from the interview, marked reported.
            best = max(responses, key=lambda r: (r["score"] or 0))
            fdef = facets_def.get(fid, {})
            facets_out[fid] = {
                "id": fid, "dimension": fdef.get("dimension", _dim_from(fid)),
                "score": best["score"], "evidence": "reported",
                "derivation": "interview: %s [%s]" % (
                    best["evidence_note"] or "", best["source_role"] or "?"),
                "inputs": {}, "gates": fdef.get("gates", []),
                "confidence": "reported"}
    store.commit()

    facets_list = [facets_out[k] for k in sorted(facets_out.keys())]

    # 3. rollup per domain, only when a target stage is declared ---------------
    domains_out = []  # type: List[dict]
    targeted = [d for d in config.get("domains", []) if d.get("target_stage")]
    if targeted:
        arc_scores = _arc_scores(by_facet, arcs_def)
        for d in targeted:
            target = d["target_stage"]
            dim_scores = dimension_rollup(facets_list, target)
            gov = governance_score(arc_scores, arcs_def, target)
            domains_out.append(
                domain_rollup(d, facets_list, dim_scores, gov))

    findings = {"facets": facets_list, "domains": domains_out}

    # 4. persist for the report step ------------------------------------------
    store.save_score_output(run_id, json.dumps(findings, sort_keys=True), now)
    store.commit()
    return findings


def _raise_int01(store, run_id, facet_id, scan_score, response, now):
    # type: (object, str, str, int, object, str) -> None
    """Interview claims a facet stronger than the scan measured. Recorded as
    INT-01, informational, with both values. Scoped by facet (stored in the
    domain slot) so simultaneous conflicts on different facets coexist."""
    evidence = {"facet": facet_id, "scan_score": scan_score,
                "interview_score": response["score"],
                "source_role": response["source_role"],
                "note": response["evidence_note"] or ""}
    store.save_flag(run_id, "INT-01", "informational", "reported", facet_id,
                    facet_id, json.dumps(evidence, sort_keys=True), 1, now)


def _arc_scores(by_facet, arcs_def):
    # type: (Dict[str, list], dict) -> Dict[str, int]
    """Governance arc scores from interview responses named governance.<arc>.
    Empty in the prototype, so governance reports as unscored."""
    scores = {}  # type: Dict[str, int]
    for facet_id, responses in by_facet.items():
        if not facet_id.startswith("governance."):
            continue
        arc = facet_id.split(".", 1)[1]
        if arc in arcs_def:
            best = max(responses, key=lambda r: (r["score"] or 0))
            if best["score"] is not None:
                scores[arc] = best["score"]
    return scores
