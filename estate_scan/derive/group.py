"""Concept grouping (build spec section 7.3, methodology section 5 step 4).

Hashing (M3) finds *identical logic*. Grouping finds the *same business metric
under different names* -- Revenue, Total Revenue, Net Rev, Rev USD -- so the
variant count a customer adjudicates is the count of concepts, not of formulas.

Three passes, each recording `method` and `confidence` on the group it forms:

  1. exact / normalized match  -- identical normalized name or identical
     resolved-formula hash. Deterministic, high confidence.
  2. token + formula signature -- conservative structural blocking plus a
     shared-base-column / shared-name-token link. Medium confidence, always
     human-reviewable.
  3. model-assisted            -- opt-in, OFF by default in the prototype
     (build brief section 6). When off, it is a recorded no-op; the local
     passes stand as the fallback.

The blocking key for pass 2 is a *structural fingerprint*: the set of
aggregation functions a resolved formula uses, and whether it is a ratio. Two
variants of one concept share computational shape; two different concepts do
not, even when they share a base column. Blocking on shape first means a
shared column such as [Sales] links revenue variants to each other without
also pulling in gross margin (a ratio) or average order value (divides by a
COUNTD). Linking is then by shared base column or shared name token *within* a
block. This is a general heuristic, not a per-metric rule set: it encodes no
knowledge of what "revenue" or "churn" means.

THE HARD RULE (build brief section 6, spec 7.3). The tool never authors a
recommended or authoritative definition. A group's `canonical_label` is only
ever an observed variant's own name or a customer-declared core-metric label;
no code path synthesizes formula text as an answer. Drafting a definition from
ambiguous source logic would encode the ambiguity while looking authoritative,
which is worse than emitting nothing.
"""

import re
from typing import Dict, List, Optional, Tuple

from estate_scan.derive.normalize import normalize

# Aggregation functions Tableau exposes. Presence of one marks a field as a
# measure-like candidate; the *set* present is half the structural fingerprint.
AGG_FUNCS = frozenset([
    "sum", "avg", "count", "countd", "min", "max", "median", "attr",
    "stdev", "stdevp", "var", "varp", "percentile", "corr", "covar",
])

# Tableau user-context / row-level-security functions. A calc field invoking one
# is an entitlement construct, not a business-metric variant, so it is excluded
# from concept grouping (it surfaces under SEC-01 instead). Kept in sync with the
# scanner the flag engine uses; defined here so `derive` owns its own predicate
# rather than importing from the fixture generator.
USER_CONTEXT_FUNCS = ["USERNAME", "ISMEMBEROF", "FULLNAME", "USERDOMAIN"]

_UC_RE = re.compile(r"\b(" + "|".join(USER_CONTEXT_FUNCS) + r")\s*\(", re.IGNORECASE)
_IDENT_RE = re.compile(r"\[([^\]]*)\]")
_STR_RE = re.compile(r'"[^"]*"')
_DATE_RE = re.compile(r"#[^#]*#")
_WORD_RE = re.compile(r"[a-z_]\w*")
_NAME_TOKEN_RE = re.compile(r"[a-z]{2,}")

# Confidence / method vocabulary, persisted per group.
HIGH, MEDIUM, LOW = "high", "medium", "low"
M_EXACT, M_TOKEN, M_MODEL = "exact_match", "formula_token", "model_assisted"


# ---------------------------------------------------------------------------
# Structural fingerprint.
# ---------------------------------------------------------------------------
def _signature(resolved_formula):
    # type: (Optional[str]) -> Tuple[frozenset, frozenset, bool]
    """Return (base_columns, agg_functions, has_ratio) for a resolved formula.

    Reads the *resolved* formula so a nested variant exposes the base columns
    of its whole chain, not just its immediate reference.
    """
    norm = normalize(resolved_formula or "")
    cols = frozenset(c.strip() for c in _IDENT_RE.findall(norm) if c.strip())
    # Strip literal / identifier content before scanning for function words, so
    # a column named like a function cannot be mistaken for an aggregation.
    stripped = _DATE_RE.sub(" ", _STR_RE.sub(" ", _IDENT_RE.sub(" ", norm)))
    words = set(_WORD_RE.findall(stripped))
    funcs = frozenset(words & AGG_FUNCS)
    has_ratio = "/" in stripped
    return cols, funcs, has_ratio


def _name_tokens(name):
    # type: (Optional[str]) -> frozenset
    return frozenset(_NAME_TOKEN_RE.findall((name or "").lower()))


def _is_candidate(row):
    # type: (dict) -> bool
    """A grouping candidate is a calculated field that computes a measure and is
    not an entitlement / row-level-security field. USERNAME/ISMEMBEROF/etc.
    fields are security constructs, not business-metric variants, so they are
    excluded from concept grouping (they surface under SEC-01 instead).

    A measure aggregates at least one base column. An aggregation wrapping only a
    literal -- MAX(0.48), AVG(75) -- is a goal/threshold constant, not a business
    metric, so it is not a candidate: grouping it produces a one-variant "concept"
    that reads as a metric with a single definition, which is noise, not a
    finding. Requiring a base column keeps the candidate set to fields that
    actually compute over the estate's data."""
    formula = row["formula"] or ""
    if _UC_RE.search(formula):
        return False
    cols, funcs, _ = _signature(row["resolved_formula"])
    return bool(funcs) and bool(cols)


# ---------------------------------------------------------------------------
# Union-find.
# ---------------------------------------------------------------------------
class _DSU(object):
    __slots__ = ("parent",)

    def __init__(self, items):
        # type: (List[str]) -> None
        self.parent = {x: x for x in items}

    def find(self, x):
        # type: (str) -> str
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        # path compression
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        # type: (str, str) -> None
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # deterministic: smaller id becomes the root
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


# ---------------------------------------------------------------------------
# Grouping.
# ---------------------------------------------------------------------------
def _label_for(members, core_metrics):
    # type: (List[dict], List[str]) -> str
    """Choose a group label: the declared core metric whose tokens best match
    the members' names, else the member name carrying the most usage. Never a
    synthesized definition."""
    name_tokens = set()
    for m in members:
        name_tokens |= _name_tokens(m["name"])
    best_metric, best_score = None, 0
    for cm in core_metrics or []:
        cm_tokens = set(_NAME_TOKEN_RE.findall(cm.lower().replace("_", " ")))
        score = len(cm_tokens & name_tokens)
        if score > best_score:
            best_metric, best_score = cm, score
        elif score == best_score and score > 0 and best_metric is not None:
            best_metric = None  # tie -> no confident metric label
    if best_metric is not None and best_score > 0:
        return best_metric
    # Fallback: the highest-usage variant's own name (observed, not authored).
    ranked = sorted(members, key=lambda m: (-m.get("_views", 0), m["field_id"]))
    return ranked[0]["name"] if ranked else ""


def assign_groups(store, run_id, core_metrics=None, model_pass=False):
    # type: (object, str, Optional[List[str]], bool) -> dict
    """Partition calculated fields into concept groups and persist them.

    Writes `metric_groups` (label / method / confidence) and the membership rows
    of `metric_variants` (group_id, field_id, normalized_hash). Usage ranking and
    dominance are filled by `rank.py`; here view counts are attached only to pick
    a label. Returns an instrumentation summary.
    """
    core_metrics = core_metrics or []
    rows = [dict(r) for r in store.calc_fields_resolved(run_id)]
    views = store.field_view_counts(run_id)
    for r in rows:
        r["_views"] = views.get(r["field_id"], {}).get("views", 0)

    candidates = [r for r in rows if _is_candidate(r)]
    excluded = len(rows) - len(candidates)

    # -- pass 1: exact clusters (identical normalized name OR resolved hash) ---
    ids = [r["field_id"] for r in candidates]
    by_id = {r["field_id"]: r for r in candidates}
    exact = _DSU(ids)
    name_key = {}  # type: Dict[str, str]
    hash_key = {}  # type: Dict[str, str]
    for r in candidates:
        nk = normalize(r["name"])
        if nk:
            if nk in name_key:
                exact.union(r["field_id"], name_key[nk])
            else:
                name_key[nk] = r["field_id"]
        hk = r.get("normalized_hash") or ""
        if hk:
            if hk in hash_key:
                exact.union(r["field_id"], hash_key[hk])
            else:
                hash_key[hk] = r["field_id"]
    exact_root = {i: exact.find(i) for i in ids}

    # -- pass 2: structural blocking + shared column / name-token linking ------
    merged = _DSU(ids)
    for i in ids:
        merged.union(i, exact_root[i])  # carry pass-1 clusters forward
    # bucket by structural fingerprint (agg-function set, is-ratio)
    blocks = {}  # type: Dict[Tuple[frozenset, bool], List[str]]
    sig_of = {}  # type: Dict[str, Tuple[frozenset, frozenset, bool]]
    for r in candidates:
        cols, funcs, ratio = _signature(r["resolved_formula"])
        sig_of[r["field_id"]] = (cols, funcs, ratio)
        blocks.setdefault((funcs, ratio), []).append(r["field_id"])
    for key, block_ids in blocks.items():
        col_index = {}  # type: Dict[str, str]
        tok_index = {}  # type: Dict[str, str]
        for fid in block_ids:
            cols = sig_of[fid][0]
            for c in cols:
                if c in col_index:
                    merged.union(fid, col_index[c])
                else:
                    col_index[c] = fid
            for t in _name_tokens(by_id[fid]["name"]):
                if t in tok_index:
                    merged.union(fid, tok_index[t])
                else:
                    tok_index[t] = fid

    # -- pass 3: model-assisted -- opt-in, off by default ---------------------
    # No merges performed. Recorded so the run metadata is honest about which
    # passes ran; the deterministic passes stand as the fallback.
    model_pass_used = bool(model_pass)

    # -- assemble groups -------------------------------------------------------
    comp = {}  # type: Dict[str, List[dict]]
    for r in candidates:
        comp.setdefault(merged.find(r["field_id"]), []).append(r)

    # deterministic group ordering: larger groups first, then by root id
    ordered_roots = sorted(comp.keys(), key=lambda root: (-len(comp[root]), root))

    store.clear_groups(run_id)
    method_counts = {M_EXACT: 0, M_TOKEN: 0}
    groups_out = []  # type: List[dict]
    for n, root in enumerate(ordered_roots, start=1):
        members = comp[root]
        # method: if every member shares one pass-1 exact cluster, the group is
        # exact/high; if pass 2 fused distinct exact clusters, it is token/medium.
        distinct_exact = set(exact_root[m["field_id"]] for m in members)
        if len(distinct_exact) == 1:
            method, confidence = M_EXACT, HIGH
        else:
            method, confidence = M_TOKEN, MEDIUM
        method_counts[method] += 1
        group_id = "grp_%04d" % n
        label = _label_for(members, core_metrics)
        store.save_metric_group(run_id, group_id, label, confidence, method)
        for m in members:
            store.save_metric_variant(
                run_id, group_id, m["field_id"], m.get("normalized_hash") or "",
                None, 0, 0, 0)
        groups_out.append({"group_id": group_id, "label": label,
                           "size": len(members), "method": method,
                           "confidence": confidence})

    store.commit()
    return {
        "groups": len(groups_out),
        "candidates": len(candidates),
        "excluded_fields": excluded,
        "method_counts": method_counts,
        "model_pass": model_pass_used,
        "detail": groups_out,
    }
