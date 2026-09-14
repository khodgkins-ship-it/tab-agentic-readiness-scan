"""Dimension and domain rollup (build spec sections 9.3 and 9.4).

Two rollup rules by dimension type, then a per-domain register. There is NO
composite across domains and NO average of dimension scores anywhere -- the
output names the binding constraint, which is the thing the whole assessment
exists to find (build spec section 9.5).
"""

from typing import Dict, List, Optional, Tuple

# The seven framework dimensions (build spec / framework Part 2). Every dimension
# with no scored gating facet at the target reports as unscored, never as clean.
DIMENSIONS = ["data", "semantic", "action_surface", "governance",
              "operating_model", "adoption", "value"]

# Governance is the one dimension that does not roll up by minimum.
GOVERNANCE = "governance"


def dimension_rollup(facets, target_stage):
    # type: (List[dict], int) -> Dict[str, dict]
    """For each supply/organizational dimension, the level is the minimum across
    facets gating entry into the target stage. Facets gating lower transitions
    are reported but do not cap. Governance is handled separately.

    Returns dimension id -> {score, gating_facets:[ids at the minimum]} for
    dimensions that HAVE a gating facet at the target; dimensions with none are
    absent (they roll up as unscored)."""
    out = {}  # type: Dict[str, dict]
    by_dim = {}  # type: Dict[str, List[dict]]
    for f in facets:
        if f["dimension"] == GOVERNANCE:
            continue
        if target_stage in (f.get("gates") or []):
            by_dim.setdefault(f["dimension"], []).append(f)

    for dim, gating in by_dim.items():
        low = min(f["score"] for f in gating)
        binding = sorted(f["id"] for f in gating if f["score"] == low)
        out[dim] = {"score": low, "gating_facets": binding}
    return out


def governance_score(arc_scores, arcs_def, target_stage):
    # type: (Dict[str, int], dict, int) -> Optional[int]
    """Governance scores at the highest stage whose loop closes completely:
    every arc active at that stage reaches the tier the stage demands (tier ==
    the stage being tested). Returns None when no arc is scored (the prototype
    case), so governance reports as unscored rather than as a closed loop."""
    if not arc_scores:
        return None
    for stage in range(6, 1, -1):
        active = [a for a, spec in arcs_def.items()
                  if stage >= spec.get("activates_at", 2)]
        if all(arc_scores.get(a, 0) >= stage for a in active):
            return stage
    return 1


def domain_rollup(domain, facets, dim_scores, gov_score):
    # type: (dict, List[dict], Dict[str, dict], Optional[int]) -> dict
    """Assemble one domain's readiness register (build spec 9.4/9.6).

    readiness = min across scored dimensions. binding_constraints = every facet
    at that minimum (ties are emitted in full, since two simultaneous
    constraints change the remediation plan). No composite, no average."""
    target = domain["target_stage"]

    scored = {}  # type: Dict[str, int]
    binding_by_dim = {}  # type: Dict[str, List[str]]
    for dim, info in dim_scores.items():
        scored[dim] = info["score"]
        binding_by_dim[dim] = info["gating_facets"]
    if gov_score is not None:
        scored[GOVERNANCE] = gov_score

    unscored = sorted(d for d in DIMENSIONS if d not in scored)

    if not scored:
        # Nothing measurable gates the target: readiness is undetermined, and
        # saying so honestly beats emitting a number with no support.
        return {"id": domain["id"], "target_stage": target,
                "readiness": None, "gap": None, "dimension_scores": {},
                "binding_constraints": [], "unscored_dimensions": unscored,
                "confidence": "unscored"}

    readiness = min(scored.values())
    binding = []  # type: List[str]
    for dim, score in scored.items():
        if score == readiness:
            binding.extend(binding_by_dim.get(dim, []))
    binding = sorted(set(binding))

    confidence = _domain_confidence(facets, binding)

    return {"id": domain["id"], "target_stage": target,
            "readiness": readiness, "gap": target - readiness,
            "dimension_scores": dict(sorted(scored.items())),
            "binding_constraints": binding,
            "unscored_dimensions": unscored,
            "confidence": confidence}


def _domain_confidence(facets, binding):
    # type: (List[dict], List[str]) -> str
    """observed when every gating facet came from the scan; mixed when any came
    from an interview; reported when the binding constraint itself is
    interview-derived (build spec 9.6)."""
    ev = {f["id"]: f.get("evidence", "observed") for f in facets}
    if any(ev.get(b) in ("reported", "interview") for b in binding):
        return "reported"
    gating_ev = [f.get("evidence", "observed") for f in facets
                 if f["id"] in binding]
    if any(e in ("reported", "interview") for e in gating_ev):
        return "mixed"
    return "observed"
