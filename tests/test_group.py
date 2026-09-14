"""M4 acceptance (build brief section 5):

  - revenue groups to 47 variants, 3 covering 80% of views, dominance true
  - active customer groups to 14 variants, dominance false
  - the four differently-named revenue variants land in one group

The pipeline must REDISCOVER these from field names, resolved formulas, and the
usage_events join alone -- the fixture client strips the `_`-prefixed ground
truth, so grouping cannot read the answer. The manifest is the assertion target.
"""

import json
import os

import pytest

from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.group import assign_groups
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


# -- acceptance: revenue -----------------------------------------------------

def test_revenue_groups_to_47_with_3_covering_80pct_and_dominant():
    store, _, _ = _grouped_store("median")
    expected = _manifest("median")["metric_groups"]["revenue"]

    g, member_names, members = _group_of(store, "Revenue")
    assert len(members) == expected["variants"] == 47, len(members)

    cover80 = cover80_for(store, "r", g["group_id"])
    assert cover80 == expected["variants_covering_80pct_views"] == 3, cover80

    # dominance is carried by is_dominant on the rank-1 variant
    dom = [m for m in members if m["is_dominant"]]
    assert len(dom) == 1 and expected["dominant"] is True
    top = min(members, key=lambda m: m["usage_rank"])
    assert top["is_dominant"] == 1 and top["usage_rank"] == 1


def test_four_named_revenue_variants_share_one_group():
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
    assert len(set(group_ids.values())) == 1, group_ids


# -- acceptance: active customer ---------------------------------------------

def test_active_customer_groups_to_14_not_dominant():
    store, _, _ = _grouped_store("median")
    expected = _manifest("median")["metric_groups"]["active_customer"]

    g, member_names, members = _group_of(store, "Customers Active")
    assert len(members) == expected["variants"] == 14, member_names
    dom = [m for m in members if m["is_dominant"]]
    assert not dom and expected["dominant"] is False


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


# -- instrumentation the build brief asks be emitted -------------------------

def test_rank_summary_emits_distributions_for_calibration():
    _, _, rank_summary = _grouped_store("median")
    assert "variant_count_distribution" in rank_summary
    assert "dominance_ratios" in rank_summary
    # revenue is the one dominant group in the median fixture
    assert rank_summary["dominant_groups"] == 1, rank_summary["dominant_groups"]
