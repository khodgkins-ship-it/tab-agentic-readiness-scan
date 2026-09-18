"""Concept grouping (build spec section 7.3, methodology section 5 step 4).

Hashing (M3) finds *identical logic*. Grouping finds definitions of one
business metric so the variant count a customer adjudicates is the count of
concepts, not of raw formulas.

Two tiers of grouping, each recording `method` and `confidence`:

  1. formula signature  -- the deterministic backbone. Each field is bucketed
     by its *canonical formula signature*: the set of aggregation functions it
     uses, the set of base columns it aggregates, and whether it is a ratio.
     Fields that compute the same measure over the same inputs the same way
     land in one bucket. A bucket whose members all carry one resolved-formula
     hash is identical logic (high confidence); a bucket spanning several
     hashes is structurally equivalent but not byte-identical (medium).
  2. model-assisted     -- opt-in, OFF by default in the prototype (build brief
     section 6). When off, it is a recorded no-op; tier 1 stands as the
     fallback.

Why exact-key bucketing rather than transitive linking. An earlier design
linked fields that shared a single base column *or* a single name token and
stitched those links with union-find. On a templated estate (Tableau
accelerators) that chains catastrophically: a date-spine column such as
[Current Year] appears in thousands of unrelated KPI fields, and templating
name tokens (value, total, perf, vs, mtd) appear in thousands more, so a single
shared boilerplate item fuses thousands of distinct calculations into one
spurious "concept." Frequency cannot separate a real metric noun from
boilerplate -- a fixture's essential link column can be more common than a live
estate's worst hub -- so the distinction is semantic, not structural. Exact
signature bucketing sidesteps this entirely: a field joins exactly one bucket,
so a shared column or token can never chain distinct concepts together.

The deliberate cost is under-grouping. Differently-*named* variants of one
metric that also differ in formula shape -- Net Rev = SUM([Sales]) - SUM([Discount])
vs Revenue = SUM([Sales]) -- are NOT merged by tier 1: they have different
signatures. Merging them is a semantic judgment ("these two differently-shaped
formulas mean the same business metric") that no frequency or structural rule
can make safely, so it is reserved for the opt-in model pass. Tier 1 errs
toward showing a concept's variants separately rather than fabricating a merge
of unrelated calculations -- precision over recall.

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

# Name tokens that carry no metric meaning: articles, prepositions, conjunctions.
# A field whose only overlap with a core metric is one of these must never fold
# into that metric's concept -- "Number of Deals" is not "Cost of Revenue" merely
# because both contain "of". Kept small and generic: function words only, never
# domain nouns.
_STOP_TOKENS = frozenset([
    "of", "the", "an", "and", "or", "to", "in", "on", "at", "by", "for",
    "per", "vs", "with", "from", "as", "is", "not", "no",
])

# Confidence / method vocabulary, persisted per group.
HIGH, MEDIUM, LOW = "high", "medium", "low"
M_EXACT, M_STRUCT, M_MODEL = "exact_match", "formula_signature", "model_assisted"


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


def _sig_key(cols, funcs, has_ratio):
    # type: (frozenset, frozenset, bool) -> str
    """A stable string form of a signature -- the unit of *one definition*.

    Two fields share a definition_key exactly when they share a signature: same
    aggregation functions over the same base columns, ratio or not. Within a
    concept group, the count of distinct definition_keys is "defined N ways", and
    rank.py decides dominance over these keys (not over individual fields), so a
    definition split across many fields is still recognised as one definition."""
    return "funcs=%s|ratio=%d|cols=%s" % (
        ",".join(sorted(funcs)), int(has_ratio), ",".join(sorted(cols)))


def _singular(token):
    # type: (str) -> str
    """Fold a trailing plural 's' so "customers" matches "customer". Leaves short
    tokens and "ss" endings ("gross", "loss") intact."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _content_tokens(name):
    # type: (Optional[str]) -> frozenset
    """The metric-bearing tokens of a name: alphabetic, >= 3 chars, not a stop
    word, singularised. Two-letter tokens and function words are dropped -- they
    are boilerplate or abbreviations, never a metric noun -- so a stop word like
    "of" can never be the thing two names share."""
    return frozenset(
        _singular(t) for t in _NAME_TOKEN_RE.findall((name or "").lower())
        if len(t) >= 3 and t not in _STOP_TOKENS)


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
# Grouping.
# ---------------------------------------------------------------------------
def _core_token_sets(core_metrics):
    # type: (List[str]) -> List[Tuple[str, frozenset, frozenset]]
    """Precompute, per declared core metric, ``(label, tokens, distinctive)``.

    ``tokens`` is the metric label's content tokens; ``distinctive`` is the subset
    of those tokens owned by NO other core metric. A distinctive token is the
    metric's own name-noun ("churn" for churn_rate, "gross" for gross_margin) --
    the thing that actually identifies it -- as opposed to a generic modifier a
    whole family shares ("rate" across churn/win/conversion rate; "revenue" across
    revenue and cost-of-revenue). A metric whose tokens are all boilerplate (empty
    set) can never match, so it is dropped."""
    prepared = []
    owners = {}  # type: Dict[str, int]
    for cm in core_metrics or []:
        toks = _content_tokens(cm.replace("_", " "))
        if toks:
            prepared.append((cm, toks))
            for t in toks:
                owners[t] = owners.get(t, 0) + 1
    return [(label, toks, frozenset(t for t in toks if owners[t] == 1))
            for label, toks in prepared]


def _core_match(name, core_token_sets):
    # type: (Optional[str], List[Tuple[str, frozenset, frozenset]]) -> Optional[str]
    """The single declared core metric this field's NAME names, or None.

    Best-match over declared core metrics, decided per FIELD from the field's own
    name (so a stray member can never relabel the whole signature bucket it shares
    -- the pooled-bucket defect). Stop words and sub-3-char tokens are excluded
    before matching, so "of" alone can never fuse "Number of Deals" into "Cost of
    Revenue" (the single-stop-word defect).

    Each candidate metric is scored by how completely the field NAMES it:
    coverage (share of the metric's tokens present), then raw shared-token count.
    The best metric wins only if it strictly beats the runner-up on that key -- a
    tie is ambiguous and folds into neither (THE HARD RULE, the tool never guesses
    which was meant). And a win must be *anchored*: the shared tokens either cover
    the metric fully, or include a token distinctive to it. That anchor is what
    stops a lone generic modifier from folding an unrelated field -- "Sales Tax"
    shares only the family token "sales" with Sales Velocity (partial, no
    distinctive token), so it folds into neither, while "Monthly Churn" shares the
    distinctive "churn" and correctly folds into churn_rate."""
    ntok = _content_tokens(name)
    if not ntok:
        return None
    scored = []
    for label, ctoks, distinctive in core_token_sets:
        shared = ctoks & ntok
        if not shared:
            continue
        anchored = shared == ctoks or bool(shared & distinctive)
        scored.append((len(shared) / float(len(ctoks)), len(shared),
                       anchored, label))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    top = scored[0]
    if not top[2]:  # winner not anchored -> generic-token-only match, refuse
        return None
    if len(scored) >= 2 and (scored[1][0], scored[1][1]) == (top[0], top[1]):
        return None  # tie on (coverage, shared count) -> ambiguous, fold neither
    return top[3]


def assign_groups(store, run_id, core_metrics=None, model_pass=False):
    # type: (object, str, Optional[List[str]], bool) -> dict
    """Partition calculated fields into concept groups and persist them.

    Writes `metric_groups` (label / method / confidence) and the membership rows
    of `metric_variants` (group_id, field_id, normalized_hash). Usage ranking and
    dominance are filled by `rank.py`; here view counts are attached only to pick
    a label. Returns an instrumentation summary.
    """
    core_metrics = core_metrics or []
    core_token_sets = _core_token_sets(core_metrics)
    rows = [dict(r) for r in store.calc_fields_resolved(run_id)]
    views = store.field_view_counts(run_id)
    for r in rows:
        r["_views"] = views.get(r["field_id"], {}).get("views", 0)

    candidates = [r for r in rows if _is_candidate(r)]
    excluded = len(rows) - len(candidates)

    # -- step 1: signature + core-label per field -----------------------------
    # Each field gets a canonical signature (agg-function set, base-column set,
    # is-ratio) -- its *definition* -- and, from its OWN name, the single declared
    # core metric it names, if any (per-field, so no member can relabel another).
    for r in candidates:
        cols, funcs, ratio = _signature(r["resolved_formula"])
        r["_defkey"] = _sig_key(cols, funcs, ratio)
        r["_sigkey"] = (funcs, ratio, cols)
        r["_core"] = _core_match(r["name"], core_token_sets)

    # -- step 2: fold definitions into concepts -------------------------------
    # A business metric is defined more than once when several fields NAME the
    # same declared core metric (e.g. "revenue defined seven ways" is one row, not
    # seven). The fold key is that core label -- a curated, human-declared name,
    # matched per field by full content-token coverage -- so folding can never
    # chain unrelated fields the way the old union-find (or single-token matching)
    # did (see module docstring). A field that names no core metric stays its own
    # concept keyed by its exact signature, so two unrelated fields that happen to
    # share a generic fallback name are never fused. Multiplicity is thus measured
    # at the concept level while signature precision is preserved underneath.
    concepts = {}  # type: Dict[object, dict]
    for r in candidates:
        ckey = ("core", r["_core"]) if r["_core"] else ("solo", r["_sigkey"])
        c = concepts.get(ckey)
        if c is None:
            concepts[ckey] = {"label": r["_core"], "members": [r]}
        else:
            c["members"].append(r)

    # A solo concept is labelled by its highest-usage member's own name (observed,
    # never a synthesized definition -- THE HARD RULE). Core concepts already carry
    # the declared label.
    for c in concepts.values():
        if c["label"] is None:
            ranked = sorted(c["members"],
                            key=lambda m: (-m.get("_views", 0), m["field_id"]))
            c["label"] = ranked[0]["name"] if ranked else ""

    # -- tier 2: model-assisted -- opt-in, off by default ---------------------
    # No merges performed. Recorded so the run metadata is honest about which
    # tiers ran; step 1 + the core-metric fold stand as the deterministic
    # backbone. A future model pass would merge differently-shaped concepts it
    # judges to be one business metric even without a shared declared label.
    model_pass_used = bool(model_pass)

    # deterministic group ordering: larger concepts first, then by the smallest
    # member field_id (stable regardless of scan/iteration order).
    ordered = sorted(
        concepts.values(),
        key=lambda c: (-len(c["members"]), min(m["field_id"] for m in c["members"])))

    store.clear_groups(run_id)
    method_counts = {M_EXACT: 0, M_STRUCT: 0}
    groups_out = []  # type: List[dict]
    for n, concept in enumerate(ordered, start=1):
        members = concept["members"]
        # A concept whose members all carry one resolved-formula hash is
        # identical logic (exact/high); one spanning several hashes -- always the
        # case once two definitions fold together -- is structurally equivalent
        # but not byte-identical (signature/medium).
        hashes = set(m.get("normalized_hash") or "" for m in members)
        hashes.discard("")
        if len(hashes) <= 1:
            method, confidence = M_EXACT, HIGH
        else:
            method, confidence = M_STRUCT, MEDIUM
        method_counts[method] += 1
        group_id = "grp_%04d" % n
        label = concept["label"]
        definitions = len(set(m["_defkey"] for m in members))
        store.save_metric_group(run_id, group_id, label, confidence, method)
        for m in members:
            store.save_metric_variant(
                run_id, group_id, m["field_id"], m.get("normalized_hash") or "",
                m["_defkey"], None, 0, 0, 0)
        groups_out.append({"group_id": group_id, "label": label,
                           "size": len(members), "definitions": definitions,
                           "method": method, "confidence": confidence})

    store.commit()
    return {
        "groups": len(groups_out),
        "candidates": len(candidates),
        "excluded_fields": excluded,
        "method_counts": method_counts,
        "model_pass": model_pass_used,
        "detail": groups_out,
    }
