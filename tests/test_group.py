"""M4 acceptance -- concept grouping under the precision-first rewrite.

Grouping is exact formula-signature bucketing (see estate_scan/derive/group.py):
a field joins exactly one bucket keyed by (agg-function set, base-column set,
is-ratio). The load-bearing property is that the deterministic path NEVER fuses
unrelated calculations -- the failure the earlier transitive-linking design
produced on templated estates, where one shared hub column or boilerplate name
token chained thousands of distinct KPIs into one spurious "concept."

The deliberate, documented cost is under-grouping: differently-*shaped*
definitions of one business metric (Net Rev = Sales - Discount vs Revenue = Sales)
land in SEPARATE groups. Merging those is a semantic judgment reserved for the
opt-in model pass; the deterministic tiers err toward showing a concept's
definitions apart rather than fabricating a merge. So the fixture's 47 planted
revenue-named fields (15 distinct definitions -- see manifest) no longer collapse
into a single group: they surface as several signature-coherent buckets, and the
largest holds the identically-shaped plain-SUM([Sales]) definitions.

The pipeline still works from field names, resolved formulas, and the
usage_events join alone -- the fixture client strips the `_`-prefixed ground
truth, so grouping cannot read the answer. The manifest documents what was
planted; these tests assert the algorithm's honest output over it.
"""

import json
import os

import pytest

from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.group import _is_candidate, _signature, assign_groups
from estate_scan.derive.rank import cover80_for, rank_groups
from estate_scan.derive.resolve import resolve_all
from estate_scan.extract.runner import ExtractRunner
from estate_scan.store import Store

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _grouped_store(profile):
    estate = os.path.join(FIXTURES, profile, "estate.json")
    client = FixtureClient.from_path(estate)
    core_metrics = client.run_config()["core_metrics"]
    store = Store.open(":memory:")
    ExtractRunner(client, store, "r").run()
    resolve_all(store, "r")
    group_summary = assign_groups(store, "r", core_metrics=core_metrics)
    rank_summary = rank_groups(store, "r")
    return store, group_summary, rank_summary


def _manifest(profile):
    with open(os.path.join(FIXTURES, profile, "manifest.json")) as fh:
        return json.load(fh)


def _field_names(store):
    return {f["id"]: f["name"] for f in store.fields_for_run("r")}


def _resolved_formulas(store):
    return {r["field_id"]: r["resolved_formula"]
            for r in store.calc_fields_resolved("r")}


def _group_signatures(store, gid):
    """The distinct formula signatures among a group's members. A
    signature-coherent group has exactly one."""
    resolved = _resolved_formulas(store)
    return {_signature(resolved[m["field_id"]])
            for m in store.metric_variants("r", gid)}


def _group_of(store, substring):
    """The group whose members include a field whose name contains `substring`
    (case-insensitive). Returns (group_row, [member field names])."""
    names = _field_names(store)
    for g in store.metric_groups("r"):
        members = store.metric_variants("r", g["group_id"])
        member_names = [names[m["field_id"]] for m in members]
        if any(substring.lower() in n.lower() for n in member_names):
            return g, member_names, members
    raise AssertionError("no group contains a field matching %r" % substring)


# -- the deterministic path never fuses unrelated calculations ---------------

def test_every_group_is_signature_coherent():
    # THE core guarantee of the precision-first rewrite: a field joins exactly
    # one bucket keyed by its formula signature, so every group's members share
    # one (agg-functions, base-columns, is-ratio) signature. This is what stops
    # a shared hub column or boilerplate name token from chaining unrelated KPIs
    # into a spurious concept -- the failure the earlier transitive-linking
    # design produced on templated estates.
    store, _, _ = _grouped_store("median")
    for g in store.metric_groups("r"):
        sigs = _group_signatures(store, g["group_id"])
        assert len(sigs) == 1, (g["group_id"], g["canonical_label"], sigs)


# -- acceptance: revenue splits by definition shape --------------------------

def test_revenue_variants_split_by_formula_signature():
    # The 47 planted revenue-named fields carry 15 distinct definitions (see
    # manifest). Precision-first grouping does NOT collapse them into one
    # concept: differently-shaped definitions land in separate buckets. The
    # identically-shaped plain-SUM([Sales]) definitions form the largest bucket.
    store, _, _ = _grouped_store("median")

    revenue_groups = []
    for g in store.metric_groups("r"):
        members = store.metric_variants("r", g["group_id"])
        names = _field_names(store)
        if any("revenue" in names[m["field_id"]].lower()
               or names[m["field_id"]] in ("Rev Base", "Rev Net")
               for m in members):
            revenue_groups.append((g, members))

    # Not one merged group -- several signature-coherent ones.
    assert len(revenue_groups) >= 5, len(revenue_groups)

    # The largest revenue bucket is the identically-shaped plain-revenue set.
    g, members = max(revenue_groups, key=lambda gm: len(gm[1]))
    assert len(members) == 19, len(members)
    assert len(_group_signatures(store, g["group_id"])) == 1
    # It is a clean concept: one definition dominates its own usage.
    dom = [m for m in members if m["is_dominant"]]
    assert len(dom) == 1


def test_differently_shaped_revenue_variants_stay_separate():
    # Revenue = SUM([Sales]); Total Revenue = SUM([Sales]) + SUM([Shipping]);
    # Net Rev = SUM([Sales]) - SUM([Discount]); Rev USD = SUM([Sales]) * [FX Rate].
    # Four different formula shapes -> four different signatures -> four groups.
    # Deterministically merging them is a semantic judgment (they *mean* one
    # metric) reserved for the opt-in model pass; the deterministic path must
    # not fabricate that merge.
    store, _, _ = _grouped_store("median")
    names = _field_names(store)
    wanted = ["Revenue", "Total Revenue", "Net Rev", "Rev USD"]

    group_ids = {}
    for g in store.metric_groups("r"):
        member_names = {names[m["field_id"]]
                        for m in store.metric_variants("r", g["group_id"])}
        for w in wanted:
            if w in member_names:
                group_ids[w] = g["group_id"]

    missing = [w for w in wanted if w not in group_ids]
    assert not missing, "not found in any group: %s" % missing
    # Each differently-shaped variant is in its own distinct group.
    assert len(set(group_ids.values())) == 4, group_ids


# -- acceptance: active customer ---------------------------------------------

def test_active_customer_variants_split_by_formula_signature():
    # The planted active-customer fields (14 variants, 9 distinct definitions)
    # likewise split by formula shape rather than collapsing into one concept.
    # The bucket found by name is signature-coherent and not dominated.
    store, _, _ = _grouped_store("median")

    g, member_names, members = _group_of(store, "Customers Active")
    assert len(members) == 3, member_names
    assert len(_group_signatures(store, g["group_id"])) == 1
    dom = [m for m in members if m["is_dominant"]]
    assert not dom


# -- the labelling maps groups back to declared core metrics -----------------

def test_group_labels_match_declared_core_metrics():
    store, _, _ = _grouped_store("median")
    labels = {g["canonical_label"] for g in store.metric_groups("r")}
    for concept in ("revenue", "active_customer", "gross_margin",
                    "churn_rate", "average_order_value"):
        assert concept in labels, (concept, labels)


# -- the tool must never author a definition ---------------------------------

def test_no_group_carries_a_synthesized_definition():
    # canonical_label is only ever a declared core metric or an observed field
    # name -- never formula text. A '(' or '[' would betray a synthesized
    # definition leaking into the label.
    store, _, _ = _grouped_store("median")
    for g in store.metric_groups("r"):
        label = g["canonical_label"]
        assert "(" not in label and "[" not in label, label


# -- entitlement fields are excluded from grouping ---------------------------

def test_user_context_fields_are_not_grouped():
    # "Member Sales" is IF ISMEMBEROF('Sales') THEN SUM([Sales]) END: it has a
    # SUM and a [Sales] column, so without exclusion it would merge into the
    # revenue block. It must not appear in any group.
    store, group_summary, _ = _grouped_store("median")
    names = _field_names(store)
    grouped_names = set()
    for g in store.metric_groups("r"):
        for m in store.metric_variants("r", g["group_id"]):
            grouped_names.add(names[m["field_id"]])
    assert "Member Sales" not in grouped_names
    assert group_summary["excluded_fields"] >= 20


# -- a grouping candidate must aggregate a base column, not a literal --------

def test_constant_only_aggregate_is_not_a_grouping_candidate():
    # MAX(0.48), AVG(75): an aggregation wrapping only a literal is a
    # goal/threshold constant, not a business metric. Without a base-column
    # requirement it would seed a one-variant "concept" that reads as a metric
    # with a single definition -- noise, not a finding. It must not be a
    # candidate.
    assert not _is_candidate({"formula": "MAX(0.48)",
                              "resolved_formula": "MAX(0.48)"})
    assert not _is_candidate({"formula": "AVG(75)",
                              "resolved_formula": "AVG(75)"})
    # A real measure aggregates at least one base column -- still a candidate.
    assert _is_candidate({"formula": "SUM([Sales])",
                          "resolved_formula": "SUM([Sales])"})
    # A ratio over columns too (this is the gross-margin shape).
    assert _is_candidate({"formula": "SUM([Profit])/SUM([Sales])",
                          "resolved_formula": "SUM([Profit])/SUM([Sales])"})
    # A non-aggregating constant is not a candidate either (no agg function).
    assert not _is_candidate({"formula": "0.48", "resolved_formula": "0.48"})
    # Entitlement fields stay excluded regardless of columns (unchanged).
    assert not _is_candidate({
        "formula": "IF ISMEMBEROF('Sales') THEN SUM([Sales]) END",
        "resolved_formula": "IF ISMEMBEROF('Sales') THEN SUM([Sales]) END"})


# -- instrumentation the build brief asks be emitted -------------------------

def test_rank_summary_emits_distributions_for_calibration():
    _, _, rank_summary = _grouped_store("median")
    assert "variant_count_distribution" in rank_summary
    assert "dominance_ratios" in rank_summary
    # Signature bucketing yields many small coherent groups, so several carry a
    # dominant definition (not the single merged-revenue group of the old
    # design). The calibration figure is emitted; assert it is present and sane.
    assert isinstance(rank_summary["dominant_groups"], int)
    assert rank_summary["dominant_groups"] >= 1, rank_summary["dominant_groups"]
