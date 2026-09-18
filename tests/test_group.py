"""M4 acceptance -- concept-level grouping.

Grouping runs in two steps (see estate_scan/derive/group.py):

  1. formula-signature bucketing: a field joins exactly one bucket keyed by
     (agg-function set, base-column set, is-ratio). A bucket is one *definition*.
  2. concept fold: buckets that carry the SAME declared core-metric label fold
     into one concept group, so "revenue defined seven ways" is ONE row, not
     seven. Multiplicity, dominance, and the finding all operate at the concept
     level; the definition count underneath is "defined N ways".

The load-bearing safety property survives the fold: the ONLY key buckets merge
on is a confident declared core-metric label -- a curated, human-supplied name.
A bucket that falls back to an observed field name never merges with another, so
a shared hub column or boilerplate token can still never chain unrelated KPIs
into a spurious concept (the failure the earlier transitive-linking design
produced on templated estates). And folding is by declared NAME, never by
formula meaning: a differently-*named* revenue variant such as "Net Rev" or
"Rev USD" stays its own group rather than being guessed into the revenue
concept -- the tool never authors or infers a definition (THE HARD RULE).

So the fixture's planted revenue-named fields collapse into a single revenue
concept carrying several distinct definitions, while the differently-named
revenue-shaped fields remain separate concepts.

The pipeline still works from field names, resolved formulas, and the
usage_events join alone -- the fixture client strips the `_`-prefixed ground
truth, so grouping cannot read the answer. The manifest documents what was
planted; these tests assert the algorithm's honest output over it.
"""

import json
import os

import pytest

from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.group import (
    _content_tokens, _core_match, _core_token_sets, _is_candidate, _signature,
    assign_groups)
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
    signature-coherent group has exactly one; a folded concept has one per
    definition."""
    resolved = _resolved_formulas(store)
    return {_signature(resolved[m["field_id"]])
            for m in store.metric_variants("r", gid)}


def _group_definitions(store, gid):
    """The distinct definition_keys among a group's members -- the "defined N
    ways" count the finding reports."""
    return {m["definition_key"] for m in store.metric_variants("r", gid)}


# -- the deterministic path merges only on a declared core-metric label ------

def test_cross_signature_merge_only_under_a_core_metric_label():
    # THE core safety guarantee, preserved through the concept fold: a group
    # spans more than one formula signature ONLY when it is a declared
    # core-metric concept. Any group whose label is not a declared core metric is
    # a single signature bucket -- so a shared hub column or boilerplate name
    # token can still never chain unrelated KPIs into a spurious concept.
    store, _, _ = _grouped_store("median")
    core = set(FixtureClient.from_path(
        os.path.join(FIXTURES, "median", "estate.json")).run_config()[
            "core_metrics"])
    for g in store.metric_groups("r"):
        sigs = _group_signatures(store, g["group_id"])
        if len(sigs) > 1:
            assert g["canonical_label"] in core, (
                g["group_id"], g["canonical_label"], sigs)


# -- acceptance: revenue is ONE concept, defined several ways -----------------

def test_revenue_is_one_concept_defined_several_ways():
    # The planted revenue-named fields fold into a SINGLE revenue concept (not
    # one group per formula shape). Within it, the distinct formula signatures
    # are the "defined N ways" count. Usage has settled on one definition, so the
    # concept is dominant -- a documentation problem, not a governance one.
    store, _, _ = _grouped_store("median")

    revenue_groups = [g for g in store.metric_groups("r")
                      if g["canonical_label"] == "revenue"]
    assert len(revenue_groups) == 1, [g["canonical_label"] for g in revenue_groups]
    g = revenue_groups[0]
    members = store.metric_variants("r", g["group_id"])
    # One concept, many fields, several definitions. The revenue-named nested
    # chain, "Revenue"/"Total Revenue", and the "Revenue NN" fillers all fold in;
    # the chain's high-usage base definition settles the concept.
    assert len(members) == 45, len(members)
    assert len(_group_definitions(store, g["group_id"])) == 8, \
        _group_definitions(store, g["group_id"])
    # Dominance is a definition-level decision: exactly one field (the top of the
    # winning definition) carries the flag.
    dom = [m for m in members if m["is_dominant"]]
    assert len(dom) == 1


def test_differently_named_revenue_variants_stay_separate():
    # Folding is by declared NAME, never by formula meaning. "Revenue" and
    # "Total Revenue" carry the core-metric token, so they belong to the revenue
    # concept. "Net Rev" and "Rev USD" do NOT carry it: the tool must not guess
    # they *mean* revenue and merge them -- that is a semantic judgment reserved
    # for the opt-in model pass (THE HARD RULE). They stay their own concepts.
    store, _, _ = _grouped_store("median")
    names = _field_names(store)

    def group_of_name(name):
        for g in store.metric_groups("r"):
            member_names = {names[m["field_id"]]
                            for m in store.metric_variants("r", g["group_id"])}
            if name in member_names:
                return g["canonical_label"]
        raise AssertionError("not found in any group: %r" % name)

    # The revenue-named fields fold into the revenue concept.
    assert group_of_name("Revenue") == "revenue"
    assert group_of_name("Total Revenue") == "revenue"
    # The differently-named revenue-shaped fields are NOT folded in.
    assert group_of_name("Net Rev") != "revenue"
    assert group_of_name("Rev USD") != "revenue"


# -- acceptance: active customer is one contested concept --------------------

def test_active_customer_is_one_contested_concept():
    # The planted active-customer fields fold into a SINGLE concept carrying
    # several definitions. No definition has settled the concept, so it is
    # contested (no dominant field) -- the governance problem the backlog
    # surfaces first.
    store, _, _ = _grouped_store("median")

    groups = [g for g in store.metric_groups("r")
              if g["canonical_label"] == "active_customer"]
    assert len(groups) == 1, [g["canonical_label"] for g in groups]
    g = groups[0]
    members = store.metric_variants("r", g["group_id"])
    assert len(members) == 14, len(members)
    assert len(_group_definitions(store, g["group_id"])) == 8, \
        _group_definitions(store, g["group_id"])
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
    # Concept grouping yields a mix of settled and contested concepts; the
    # dominant-group count is the calibration figure. Assert it is present and
    # sane (emitted, not tuned against).
    assert isinstance(rank_summary["dominant_groups"], int)
    assert rank_summary["dominant_groups"] >= 1, rank_summary["dominant_groups"]


# -- the core-metric fold predicate, pinned directly ------------------------
# These exercise `_core_match` in isolation -- the load-bearing decision that
# folds a field into a declared concept only when its NAME names that concept.
# The fixture acceptance tests above prove the whole pipeline; these pin the four
# behaviours that keep the fold from over-reaching, so a future tweak that
# loosened any of them fails here with a precise message rather than as a distant
# fixture-count drift.

def test_content_tokens_drop_stop_words_and_short_tokens():
    # A function word ("of") and a two-letter token carry no metric meaning, so
    # they are never content tokens -- "of" alone can never be the thing two
    # names share. Plurals fold to singular so "Customers" matches "customer".
    assert _content_tokens("Number of Deals") == frozenset({"number", "deal"})
    assert _content_tokens("Rev by FX") == frozenset({"rev"})  # "by"/"FX" dropped
    assert _content_tokens("Active Customers") == frozenset({"active", "customer"})


def test_core_match_refuses_a_generic_token_only_match():
    # "rate" is shared across a whole family (churn/win/conversion), so it is not
    # distinctive to any one. A name whose ONLY overlap is that family token is
    # not anchored -> it folds into NEITHER, never guessing which was meant.
    cts = _core_token_sets(["churn_rate", "win_rate", "conversion_rate"])
    assert _core_match("Bounce Rate", cts) is None


def test_core_match_folds_on_a_distinctive_token():
    # "churn" is owned by churn_rate alone, so a name carrying it anchors and
    # folds -- even though it does not cover the metric's every token.
    cts = _core_token_sets(["churn_rate", "win_rate", "conversion_rate"])
    assert _core_match("Monthly Churn", cts) == "churn_rate"


def test_core_match_folds_on_full_coverage_via_plural():
    # Full token coverage anchors on its own; plural folding lets "Customers"
    # cover "customer".
    cts = _core_token_sets(["active_customer", "revenue"])
    assert _core_match("Active Customers", cts) == "active_customer"


def test_core_match_returns_none_on_a_tie():
    # A name that names two metrics equally well (same coverage, same shared
    # count, both anchored) is ambiguous: the tool folds into neither rather than
    # picking one -- THE HARD RULE, it never guesses a definition.
    cts = _core_token_sets(["daily_active", "monthly_active"])
    assert _core_match("Active Daily Monthly", cts) is None
