"""M3 acceptance: the hostile fixture resolves with every status class
represented and no unhandled exception; two formulas differing only in
whitespace and alias collapse to one hash; two differing in a date boundary do
not."""

import os

import pytest

from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.resolve import (CYCLE, RESOLVED, TOO_DEEP, UNRESOLVED,
                                        resolve_all)
from estate_scan.extract.runner import ExtractRunner
from estate_scan.store import Store

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _resolved_store(profile):
    estate = os.path.join(FIXTURES, profile, "estate.json")
    store = Store.open(":memory:")
    ExtractRunner(FixtureClient.from_path(estate), store, "r").run()
    summary = resolve_all(store, "r")
    return store, summary


def _by_name(store):
    names = {f["id"]: f["name"] for f in store.fields_for_run("r")}
    return {names[r["field_id"]]: r for r in store.resolved_formulas("r")}


# -- acceptance: every status class, no exception ----------------------------

def test_hostile_represents_every_status_class():
    store, summary = _resolved_store("hostile")
    counts = store.resolution_status_counts("r")
    for status in (RESOLVED, CYCLE, TOO_DEEP, UNRESOLVED):
        assert counts.get(status, 0) >= 1, (status, counts)
    # No calculated field is dropped silently: every calc field has a row.
    assert sum(counts.values()) == summary["calculated"]


def test_cycle_is_detected_not_infinite():
    rows = _by_name(_resolved_store("hostile")[0])
    assert rows["Cycle A"]["resolution_status"] == CYCLE
    assert rows["Cycle B"]["resolution_status"] == CYCLE


def test_depth_cap_marks_too_deep_at_the_boundary():
    rows = _by_name(_resolved_store("hostile")[0])
    # Deep 00..13 is a 14-link chain; the field one step past the depth-12 cap
    # is too deep, the one at the cap still resolves.
    assert rows["Deep 13"]["resolution_status"] == TOO_DEEP
    assert rows["Deep 12"]["resolution_status"] == RESOLVED


def test_dangling_reference_is_unresolved_not_dropped():
    rows = _by_name(_resolved_store("hostile")[0])
    assert rows["Dangling"]["resolution_status"] == UNRESOLVED
    # The unresolved token is left in place, not silently removed.
    assert "No Such Field" in rows["Dangling"]["resolved_formula"]


def test_resolution_is_scoped_to_the_containing_source():
    # "Uses Rev" lives in Edge DS 2 and references "Rev Base" there, which is
    # SUM([Amount]) * 2. It must resolve through that source's field, not any
    # same-named field in another source.
    rows = _by_name(_resolved_store("hostile")[0])
    resolved = rows["Uses Rev"]
    assert resolved["resolution_status"] == RESOLVED
    assert "[Amount]" in resolved["resolved_formula"]


def test_unicode_field_name_resolves():
    rows = _by_name(_resolved_store("hostile")[0])
    assert rows[u"Uses Unicode"]["resolution_status"] == RESOLVED
    assert "[Sales]" in rows[u"Uses Unicode"]["resolved_formula"]


# -- acceptance: hash behaviour on real fixture variants ---------------------

def test_whitespace_and_alias_variants_share_one_hash():
    # The revenue group in the median fixture contains SUM([Sales]) and
    # SUM( [Sales] ) under different names; after normalization they are one
    # definition.
    rows = _by_name(_resolved_store("median")[0])
    plain = rows["Revenue"]["normalized_hash"]
    spaced = rows["Revenue 02"]["normalized_hash"]
    assert plain and spaced and plain == spaced


def test_date_boundary_variants_do_not_share_a_hash():
    rows = _by_name(_resolved_store("median")[0])
    d30 = rows["Customers Active 30d"]["normalized_hash"]
    d90 = rows["Customers Active 90d"]["normalized_hash"]
    assert d30 and d90 and d30 != d90


def test_median_resolves_all_calculated_fields():
    store, summary = _resolved_store("median")
    counts = store.resolution_status_counts("r")
    # The median estate is well-formed: everything resolves, nothing dangles.
    assert counts.get(RESOLVED) == summary["calculated"]
    assert CYCLE not in counts and TOO_DEEP not in counts


def test_field_refs_are_rediscovered_from_text():
    # field_refs must be derived by parsing formula tokens, independent of the
    # stripped ground-truth _ref_field_ids.
    store, _ = _resolved_store("hostile")
    refs = store.field_refs("r")
    assert refs, "expected a rediscovered reference graph"
    names = {f["id"]: f["name"] for f in store.fields_for_run("r")}
    edges = {(names[r["field_id"]], names[r["referenced_field_id"]]) for r in refs}
    assert ("Uses Rev", "Rev Base") in edges
    assert ("Ok 4", "Ok 3") in edges
