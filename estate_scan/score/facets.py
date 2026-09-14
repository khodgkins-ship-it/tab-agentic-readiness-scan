"""Facet score derivation (build spec section 9.2).

Two paths, both driven entirely by `rules.yaml` so thresholds move without a
code edit:

  - threshold facets: a measure compared against ordered bands; the facet takes
    the highest band whose condition holds.
  - flag-capped facets: caps pull the score down when a flag fires.

The band grammar is evaluated by a small constrained parser, never by eval().
An unrecognised band expression raises rather than silently passing -- a
mis-typed threshold must fail loudly, not score a facet clean.
"""

import re
from typing import Callable, Dict, Optional, Tuple

# measure registry: name -> f(store, run_id) -> float. Domain-project scoping is
# out of prototype scope (build brief section 1), so measures are estate-wide;
# the single declared domain covers the estate.
MEASURES = {}  # type: Dict[str, Callable]


def measure(name):
    def deco(fn):
        MEASURES[name] = fn
        return fn
    return deco


@measure("dominant_variant_share")
def _m_dominant_share(store, run_id):
    dominant, total = store.dominant_group_share(run_id)
    return (dominant / float(total)) if total else 0.0


@measure("description_coverage")
def _m_description_coverage(store, run_id):
    described, total = store.field_description_coverage(run_id)
    return (described / float(total)) if total else 0.0


@measure("published_datasource_share")
def _m_published_share(store, run_id):
    emb, pub = store.workbook_ds_ref_counts(run_id)
    denom = emb + pub
    return (pub / float(denom)) if denom else 0.0


@measure("content_activation")
def _m_content_activation(store, run_id):
    total = store.workbook_count(run_id)
    zero = len(store.zero_view_workbooks(run_id))
    return ((total - zero) / float(total)) if total else 0.0


# -- band grammar ------------------------------------------------------------
_CMP_RE = re.compile(r"^(<=|>=|<|>|==)\s*(-?\d+(?:\.\d+)?)$")
_RANGE_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)$")
_BOOL_RE = re.compile(r"^(\w+)\s*==\s*(true|false)$", re.IGNORECASE)


def _eval_clause(clause, value, inputs):
    # type: (str, float, dict) -> bool
    clause = clause.strip()
    m = _CMP_RE.match(clause)
    if m:
        op, num = m.group(1), float(m.group(2))
        if op == "<":
            return value < num
        if op == "<=":
            return value <= num
        if op == ">":
            return value > num
        if op == ">=":
            return value >= num
        return value == num
    m = _RANGE_RE.match(clause)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return lo <= value <= hi
    m = _BOOL_RE.match(clause)
    if m:
        name, want = m.group(1), (m.group(2).lower() == "true")
        # An input the scan cannot observe is absent and reads false, so a
        # scan-only run never reaches a band that needs interview evidence.
        return bool(inputs.get(name, False)) is want
    raise ValueError("unrecognised band clause: %r" % clause)


def _band_holds(expr, value, inputs):
    # type: (str, float, dict) -> bool
    return all(_eval_clause(c, value, inputs)
               for c in str(expr).split(" and "))


def score_threshold(bands, value, inputs):
    # type: (dict, float, dict) -> Tuple[int, str]
    """Highest band whose condition holds; floor 1 (Minimal) if none do."""
    best, chosen = 1, "band 1 (floor): no higher band held"
    for band in sorted(bands.keys(), key=int):
        expr = bands[band]
        if _band_holds(expr, value, inputs):
            best = int(band)
            chosen = "band %s: measure %.4g satisfies %r" % (band, value, expr)
    return best, chosen


def score_capped(base, caps, flag_counts):
    # type: (int, list, Dict[str, int]) -> Tuple[int, str]
    """Apply flag caps to a base score. `flag_counts` maps flag id -> fired
    count (0 or absent = not fired). A cap fires when its `when` holds against
    that count."""
    score = base
    derivation = "base %d, no cap fired" % base
    for cap in caps or []:
        count = flag_counts.get(cap["flag"], 0)
        if _eval_clause(cap["when"], count, {}):
            if cap["max_score"] < score:
                score = cap["max_score"]
                derivation = ("capped at %d by %s (%s, count=%s)"
                              % (cap["max_score"], cap["flag"], cap["when"],
                                 count))
    return score, derivation


def score_facet(facet_id, fdef, store, run_id, inputs):
    # type: (str, dict, object, str, dict) -> Optional[dict]
    """Derive one facet from the scan. Returns the facet record, or None when
    the facet cannot be scored from the scan (no measure and no caps -- i.e.
    interview-only)."""
    gates = fdef.get("gates", [])
    dimension = fdef["dimension"]

    if "measure" in fdef:
        name = fdef["measure"]
        fn = MEASURES.get(name)
        if fn is None:
            raise ValueError("no measure %r for facet %s" % (name, facet_id))
        value = fn(store, run_id)
        score, derivation = score_threshold(fdef.get("bands", {}), value,
                                            inputs)
        return {"id": facet_id, "dimension": dimension, "score": score,
                "evidence": "observed", "derivation": derivation,
                "inputs": {name: round(value, 4)}, "gates": gates}

    if "caps" in fdef:
        flag_counts = _fired_flag_counts(store, run_id)
        base = fdef.get("base", 6)
        score, derivation = score_capped(base, fdef["caps"], flag_counts)
        return {"id": facet_id, "dimension": dimension, "score": score,
                "evidence": "observed", "derivation": derivation,
                "inputs": {c["flag"]: flag_counts.get(c["flag"], 0)
                           for c in fdef["caps"]},
                "gates": gates}

    return None


def _fired_flag_counts(store, run_id):
    # type: (object, str) -> Dict[str, int]
    """Fired flag id -> count, read from the flags the engine wrote."""
    counts = {}  # type: Dict[str, int]
    for row in store.flags(run_id):
        counts[row["flag_id"]] = max(counts.get(row["flag_id"], 0),
                                     row["count"] or 0)
    return counts
