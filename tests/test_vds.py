"""R3 acceptance: the VizQL Data Service executor and material disagreement.

Three layers, all offline (no network, no credentials):

  * the executor/client -- `build_query_body` emits only read keys, `vds_query`
    issues a read-only aggregate and parses the figure, and the capability probe
    detects VDS present/absent. Driven by the *production* `LiveClient` over a
    `FixtureTransport`, so the shipping read-only guard and parser are exercised.
  * the classifier -- `classify_variant` places each variant in the right
    executability class (an unresolved formula is never silently clean).
  * the orchestration + report join -- `resolve_material_disagreement` executes a
    seeded contested group and marks the material gap; `_definition_multiplicity`
    surfaces the figures in the working build and `redact` removes the raw values
    from the presentation build while keeping the safe diff figures.
"""

import json
import os
import re

import pytest

from estate_scan.clients.auth import Credentials
from estate_scan.clients.live import LiveClient
from estate_scan.clients.vds import VdsExecutor
from estate_scan.derive.disagreement import (
    CONTEXT_BOUND,
    EXECUTABLE,
    NOT_COMPARABLE,
    UNRESOLVABLE,
    classify_variant,
    resolve_material_disagreement,
)
from estate_scan.readonly import ReadOnlyViolation, assert_vds_body_read_only
from estate_scan.report.findings import _definition_multiplicity
from estate_scan.report.redact import REDACTED, mark_working, redact
from estate_scan.report.webapp import render_html, webapp_payload
from estate_scan.store import Store

from tests.transport import FixtureTransport

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _estate(profile="median"):
    with open(os.path.join(FIXTURES, profile, "estate.json")) as fh:
        return json.load(fh)


def _config(estate):
    return {"host": "https://fixture.online.tableau.com",
            "deployment_type": estate.get("meta", {}).get("deployment_type", "cloud"),
            "site_content_url": ""}


def _connected_client(vds_available=False, vds_values=None):
    """A production LiveClient over a FixtureTransport, connected and with
    capabilities detected -- the seam that lets the VDS path run offline."""
    estate = _estate()
    ft = FixtureTransport(estate, vds_available=vds_available,
                          vds_values=vds_values or {})
    client = LiveClient(_config(estate), transport=ft.transport,
                        credentials=Credentials("pat", "secret", "env"))
    client.connect()
    client.detect_capabilities()
    return client, ft


# -- the executor / client (over the production guard) -----------------------

def test_build_query_body_emits_only_read_keys():
    # No period filter: just a datasource reference and one measure field.
    body = VdsExecutor.build_query_body("luid-1", "Revenue", function="SUM")
    assert set(body) <= {"datasource", "query"}
    assert set(body["query"]) <= {"fields", "filters"}
    assert body["query"]["fields"] == [{"fieldCaption": "Revenue", "function": "SUM"}]
    # Passes the read-only body check by construction (never raises).
    assert_vds_body_read_only(body, label="test")


def test_build_query_body_with_period_filter_is_still_read_only():
    body = VdsExecutor.build_query_body("luid-1", "Revenue",
                                        period_field="Order Month",
                                        period_value="2024-01")
    assert set(body["query"]) <= {"fields", "filters"}
    flt = body["query"]["filters"][0]
    assert flt["filterType"] == "SET"
    assert flt["field"] == {"fieldCaption": "Order Month"}
    assert flt["values"] == ["2024-01"]
    assert_vds_body_read_only(body, label="test")  # must not raise


def test_vds_query_issues_a_read_and_parses_the_value():
    client, ft = _connected_client(
        vds_available=True, vds_values={"luid-1::Revenue": 42.5})
    try:
        body = VdsExecutor.build_query_body("luid-1", "Revenue")
        result = client.vds_query(body)
        assert result.ok
        assert result.value("Revenue") == 42.5
        # The query went out as a POST to the one query-datasource path.
        assert ("POST", "/api/v1/vizql-data-service/query-datasource") in ft.requests
    finally:
        client.close()


def test_vds_query_unknown_measure_reads_none_not_zero():
    client, _ft = _connected_client(vds_available=True, vds_values={})
    try:
        result = client.vds_query(VdsExecutor.build_query_body("luid-1", "Ghost"))
        # An empty data row is a real (ok) response with no cell for the caption.
        assert result.ok
        assert result.value("Ghost") is None
    finally:
        client.close()


def test_capability_probe_detects_vds_present():
    client, _ft = _connected_client(vds_available=True)
    try:
        assert client.capabilities["vizql_data_service"] is True
        assert VdsExecutor(client).available is True
    finally:
        client.close()


def test_capability_probe_detects_vds_absent():
    client, _ft = _connected_client(vds_available=False)
    try:
        assert client.capabilities["vizql_data_service"] is False
        assert VdsExecutor(client).available is False
    finally:
        client.close()


# -- classification ----------------------------------------------------------

def test_classify_variant_places_each_class():
    base = {"resolution_status": "resolved", "resolved_formula": "SUM([Amount])",
            "datasource_luid": "luid-1", "role": "measure"}
    assert classify_variant(dict(base))[0] == EXECUTABLE

    unresolved = dict(base, resolution_status="unresolved_reference",
                      resolved_formula=None)
    assert classify_variant(unresolved)[0] == UNRESOLVABLE

    context = dict(base, resolved_formula="IF ISMEMBEROF('Finance') THEN 1 END")
    assert classify_variant(context)[0] == CONTEXT_BOUND

    no_luid = dict(base, datasource_luid="")
    assert classify_variant(no_luid)[0] == NOT_COMPARABLE

    not_measure = dict(base, role="dimension")
    assert classify_variant(not_measure)[0] == NOT_COMPARABLE


def test_classify_variant_reports_a_reason_for_every_untested_class():
    for row in (
        {"resolution_status": "cycle", "resolved_formula": None,
         "datasource_luid": "x", "role": "measure"},
        {"resolution_status": "resolved", "resolved_formula": "USERNAME()",
         "datasource_luid": "x", "role": "measure"},
        {"resolution_status": "resolved", "resolved_formula": "SUM([x])",
         "datasource_luid": None, "role": "measure"},
    ):
        cls, reason = classify_variant(row)
        assert cls != EXECUTABLE
        assert reason  # never silently clean: an untested variant carries a reason


# -- orchestration: a seeded contested group --------------------------------

def _seed_group(store, run_id="r"):
    """One metric group with four variants: a dominant executable reference, an
    executable variant that disagrees materially, a context-bound one, and an
    unresolvable one. Seeded directly through the store's loaders."""
    store.load_datasources(run_id, [
        {"id": "ds1", "luid": "luid-1", "name": "Sales",
         "owner": {"username": "alice"}}])
    fields = [
        {"id": "f_ref", "__typename": "CalculatedField", "name": "Revenue",
         "dataType": "REAL", "role": "MEASURE", "formula": "SUM([Amount])"},
        {"id": "f_var", "__typename": "CalculatedField", "name": "RevenueV2",
         "dataType": "REAL", "role": "MEASURE", "formula": "SUM([Amt])"},
        {"id": "f_ctx", "__typename": "CalculatedField", "name": "RevenueUser",
         "dataType": "REAL", "role": "MEASURE",
         "formula": "IF USERNAME()='x' THEN [Amount] END"},
        {"id": "f_bad", "__typename": "CalculatedField", "name": "RevenueBad",
         "dataType": "REAL", "role": "MEASURE", "formula": "[Missing]"},
    ]
    store.load_fields(run_id, "ds1", fields)
    resolved = {
        "f_ref": ("SUM([Amount])", "resolved"),
        "f_var": ("SUM([Amt])", "resolved"),
        "f_ctx": ("IF USERNAME()='x' THEN [Amount] END", "resolved"),
        "f_bad": (None, "unresolved_reference"),
    }
    for fid, (rf, status) in resolved.items():
        store.save_resolved_formula(run_id, fid, rf, "h_" + fid, 1, status)
    store.save_metric_group(run_id, "g1", "revenue", "high", "exact")
    variants = [
        ("f_ref", 1, 500, 5, True),
        ("f_var", 2, 100, 2, False),
        ("f_ctx", 3, 50, 1, False),
        ("f_bad", 4, 10, 1, False),
    ]
    for fid, rank, views, wbs, dom in variants:
        # Each variant is its own definition here (distinct formulas), so the
        # definition_key is distinct per field.
        store.save_metric_variant(run_id, "g1", fid, "h_" + fid, "d_" + fid,
                                  rank, views, wbs, dom)
    store.commit()


def _material_store():
    store = Store.open(":memory:")
    _seed_group(store)
    client, _ft = _connected_client(
        vds_available=True,
        vds_values={"luid-1::Revenue": 1000.0, "luid-1::RevenueV2": 1200.0})
    try:
        summary = resolve_material_disagreement(
            store, "r", VdsExecutor(client), period="2024", tolerance=0.005,
            now="2026-01-01T00:00:00Z")
    finally:
        client.close()
    return store, summary


def test_resolve_marks_material_disagreement():
    store, summary = _material_store()
    assert summary["skipped"] is False
    assert summary["groups"] == 1
    assert summary["executed"] == 2          # only the two executable variants
    assert summary["material_groups"] == 1   # 1000 vs 1200 is 20% > 0.5%

    rows = {r["field_id"]: r for r in store.variant_execution_detail("r", "g1")}
    assert rows["f_ref"]["is_reference"] == 1
    assert rows["f_ref"]["executability_class"] == "executable"
    # The diverging variant is material; the reference is its own baseline.
    assert rows["f_var"]["material"] == 1
    assert abs(rows["f_var"]["rel_diff"] - 0.2) < 1e-9
    # The untested variants are recorded with a class + reason, never dropped.
    assert rows["f_ctx"]["executability_class"] == "context_bound"
    assert rows["f_bad"]["executability_class"] == "unresolvable"
    assert rows["f_ctx"]["value"] is None and rows["f_bad"]["value"] is None

    cov = {r["measure"]: r for r in store.coverage("r")}
    assert cov["material_disagreement"]["status"] == "ok"


def _seed_group_with_failing_reference(store, run_id="r"):
    """One contested group with three executable variants. The dominant, lowest-
    usage-rank variant -- the one `_pick_reference` would pick first -- has no
    seeded VDS value, so its query returns None (an empty/failed baseline). The
    two alternates return divergent figures (100 vs 130, a 30% gap)."""
    store.load_datasources(run_id, [{"id": "ds1", "luid": "luid-1",
                                     "name": "Sales"}])
    fields = [
        {"id": "f_dom", "__typename": "CalculatedField", "name": "Dominant",
         "dataType": "REAL", "role": "MEASURE", "formula": "SUM([A])"},
        {"id": "f_a", "__typename": "CalculatedField", "name": "AltA",
         "dataType": "REAL", "role": "MEASURE", "formula": "SUM([B])"},
        {"id": "f_b", "__typename": "CalculatedField", "name": "AltB",
         "dataType": "REAL", "role": "MEASURE", "formula": "SUM([C])"},
    ]
    store.load_fields(run_id, "ds1", fields)
    for fid, rf in (("f_dom", "SUM([A])"), ("f_a", "SUM([B])"),
                    ("f_b", "SUM([C])")):
        store.save_resolved_formula(run_id, fid, rf, "h_" + fid, 1, "resolved")
    store.save_metric_group(run_id, "g1", "revenue", "high", "exact")
    # f_dom is dominant and rank 1 -> the first-choice reference; f_a/f_b are the
    # value-returning alternates.
    store.save_metric_variant(run_id, "g1", "f_dom", "h_f_dom", "d_f_dom",
                              1, 100, 3, True)
    store.save_metric_variant(run_id, "g1", "f_a", "h_f_a", "d_f_a",
                              2, 50, 2, False)
    store.save_metric_variant(run_id, "g1", "f_b", "h_f_b", "d_f_b",
                              3, 20, 1, False)
    store.commit()


def test_resolve_reselects_reference_when_first_choice_returns_none():
    # Regression: the first-choice reference's query returns None (empty/failed).
    # Diffing against a None baseline would NULL every variant and report a false
    # "no disagreement". The reference must fall back to a value-returning variant
    # so the real 30% gap between the alternates is still caught.
    store = Store.open(":memory:")
    _seed_group_with_failing_reference(store)
    # "Dominant" is absent from vds_values -> its query returns None; the two
    # alternates return divergent figures.
    client, _ft = _connected_client(
        vds_available=True,
        vds_values={"luid-1::AltA": 100.0, "luid-1::AltB": 130.0})
    try:
        summary = resolve_material_disagreement(
            store, "r", VdsExecutor(client), period="2024", tolerance=0.005,
            now="2026-01-01T00:00:00Z")
    finally:
        client.close()

    assert summary["material_groups"] == 1
    rows = {r["field_id"]: r for r in store.variant_execution_detail("r", "g1")}
    # The failed first-choice is passed over, not made the baseline.
    assert rows["f_dom"]["is_reference"] == 0
    assert rows["f_dom"]["value"] is None
    assert rows["f_dom"]["material"] is None
    # Lowest usage rank among the value-returning variants becomes the reference.
    assert rows["f_a"]["is_reference"] == 1
    # The disagreement is now visible instead of collapsed to NULL.
    assert rows["f_b"]["material"] == 1
    assert abs(rows["f_b"]["rel_diff"] - 0.3) < 1e-9
    # No query errored (an empty result is ok=True), so coverage is clean.
    cov = {r["measure"]: r for r in store.coverage("r")}
    assert cov["material_disagreement"]["status"] == "ok"


def test_resolve_skipped_when_capability_off_records_coverage():
    store = Store.open(":memory:")
    _seed_group(store)
    client, _ft = _connected_client(vds_available=False)
    try:
        summary = resolve_material_disagreement(
            store, "r", VdsExecutor(client), period="2024")
    finally:
        client.close()
    assert summary["skipped"] is True
    # Unmeasured, not clean: no rows written, coverage says skipped with a reason.
    assert store.count("variant_execution", "r") == 0
    cov = {r["measure"]: r for r in store.coverage("r")}
    assert cov["material_disagreement"]["status"] == "skipped"
    assert cov["material_disagreement"]["reason"]


# -- the budget cap (top N groups / M queries, whichever binds) --------------

def _seed_two_groups(store, run_id="r"):
    """Two groups whose group_ids sort the *opposite* way to their adjudication
    priority, so a cap that keeps only the top group proves the contested-first
    ordering is used (not raw group_id order):

      * ``g_z_contested`` -- two distinct used definitions, neither dominant ->
        *contested* (highest priority), two executable variants (2 queries);
      * ``g_a_singular`` -- one definition -> *singular* (lowest priority), one
        executable variant (1 query).

    Usage is recorded measured so dominance is determinable (else both would be
    ``unmeasured`` and the split under test would not exist)."""
    store.record_coverage(run_id, "usage_events", "ok", "seeded for the test")
    store.load_datasources(run_id, [{"id": "ds1", "luid": "luid-1", "name": "Sales"}])
    fields = [
        {"id": "hi_a", "__typename": "CalculatedField", "name": "HiA",
         "dataType": "REAL", "role": "MEASURE", "formula": "SUM([Amount])"},
        {"id": "hi_b", "__typename": "CalculatedField", "name": "HiB",
         "dataType": "REAL", "role": "MEASURE", "formula": "SUM([Amt])"},
        {"id": "lo_a", "__typename": "CalculatedField", "name": "LoA",
         "dataType": "REAL", "role": "MEASURE", "formula": "SUM([Qty])"},
    ]
    store.load_fields(run_id, "ds1", fields)
    for fid, rf in (("hi_a", "SUM([Amount])"), ("hi_b", "SUM([Amt])"),
                    ("lo_a", "SUM([Qty])")):
        store.save_resolved_formula(run_id, fid, rf, "h_" + fid, 1, "resolved")
    store.save_metric_group(run_id, "g_z_contested", "high", "high", "exact")
    store.save_metric_group(run_id, "g_a_singular", "low", "high", "exact")
    # contested: two definitions, both carry usage, neither dominant.
    store.save_metric_variant(run_id, "g_z_contested", "hi_a", "h_hi_a", "d_hi_a",
                              1, 100, 3, False)
    store.save_metric_variant(run_id, "g_z_contested", "hi_b", "h_hi_b", "d_hi_b",
                              2, 80, 2, False)
    # singular: one definition (dominant, but a single definition is not a contest).
    store.save_metric_variant(run_id, "g_a_singular", "lo_a", "h_lo_a", "d_lo_a",
                              1, 50, 1, True)
    store.commit()


def _run_two(store, max_groups, max_queries):
    client, _ft = _connected_client(
        vds_available=True,
        vds_values={"luid-1::HiA": 100.0, "luid-1::HiB": 120.0,
                    "luid-1::LoA": 50.0})
    try:
        return resolve_material_disagreement(
            store, "r", VdsExecutor(client), period="2024",
            now="2026-01-01T00:00:00Z",
            max_groups=max_groups, max_queries=max_queries)
    finally:
        client.close()


def _ran_group_ids(store, run_id="r"):
    return {r["group_id"] for r in store.conn.execute(
        "SELECT DISTINCT group_id FROM variant_execution WHERE run_id=?",
        (run_id,)).fetchall()}


def test_budget_cap_max_groups_keeps_top_priority_group():
    store = Store.open(":memory:")
    _seed_two_groups(store)
    summary = _run_two(store, max_groups=1, max_queries=1000)
    assert summary["groups"] == 1
    assert "group cap" in summary["capped"]
    # The contested group ran despite sorting *after* the singular one by
    # group_id -- so the run followed the report's contested-first priority.
    assert _ran_group_ids(store) == {"g_z_contested"}
    cov = {r["measure"]: r for r in store.coverage("r")}
    assert cov["material_disagreement"]["status"] == "partial"
    assert "group cap" in cov["material_disagreement"]["reason"]


def test_budget_cap_query_cap_blocks_the_next_group():
    store = Store.open(":memory:")
    _seed_two_groups(store)
    # The contested group's two queries fit exactly; the singular group's one more
    # would cross the budget, so it is left un-run (whole-group, never partial).
    summary = _run_two(store, max_groups=10, max_queries=2)
    assert summary["groups"] == 1
    assert summary["executed"] == 2
    assert "query cap" in summary["capped"]
    assert _ran_group_ids(store) == {"g_z_contested"}
    cov = {r["measure"]: r for r in store.coverage("r")}
    assert cov["material_disagreement"]["status"] == "partial"


def test_budget_cap_is_group_atomic_when_top_group_alone_exceeds_budget():
    store = Store.open(":memory:")
    _seed_two_groups(store)
    # The top group needs two queries but the budget is one: a group is never
    # half-run, so nothing executes rather than the reference alone.
    summary = _run_two(store, max_groups=10, max_queries=1)
    assert summary["groups"] == 0
    assert summary["executed"] == 0
    assert "query cap" in summary["capped"]
    assert store.count("variant_execution", "r") == 0
    cov = {r["measure"]: r for r in store.coverage("r")}
    assert cov["material_disagreement"]["status"] == "partial"


def test_no_budget_cap_runs_every_group_and_records_ok():
    store = Store.open(":memory:")
    _seed_two_groups(store)
    summary = _run_two(store, max_groups=10, max_queries=1000)
    assert summary["groups"] == 2
    assert summary["capped"] is None
    assert _ran_group_ids(store) == {"g_z_contested", "g_a_singular"}
    cov = {r["measure"]: r for r in store.coverage("r")}
    assert cov["material_disagreement"]["status"] == "ok"


# -- the report join + redaction ---------------------------------------------

def test_findings_join_surfaces_execution_and_redaction_removes_raw_values():
    store, _summary = _material_store()
    dm = _definition_multiplicity(store, "r")
    group = dm["groups"][0]

    # Working build: the group rollup and per-variant figures are present.
    assert "execution" in group
    ex = group["execution"]
    assert ex["reference_field"] == "Revenue"
    assert ex["material_disagreement"] is True
    assert ex["most_material_pair"]["variant_field"] == "RevenueV2"
    assert ex["most_material_pair"]["reference_value"] == 1000.0
    assert ex["most_material_pair"]["variant_value"] == 1200.0

    var_by_name = {v["field_name"]: v for v in group["variants"]}
    assert var_by_name["Revenue"]["execution"]["value"] == 1000.0
    assert var_by_name["RevenueV2"]["execution"]["value"] == 1200.0
    assert var_by_name["RevenueV2"]["execution"]["material"] is True

    # Presentation build: raw values redacted, safe diff figures kept.
    findings = {"meta": {}, "findings": {"definition_multiplicity": dm,
                                         "security_exposure": {}}}
    pres = redact(findings)
    pg = pres["findings"]["definition_multiplicity"]["groups"][0]
    assert pg["execution"]["most_material_pair"]["reference_value"] == REDACTED
    assert pg["execution"]["most_material_pair"]["variant_value"] == REDACTED
    # abs_diff / rel_diff / material survive redaction -- they are safe to show.
    assert abs(pg["execution"]["most_material_pair"]["rel_diff"] - 0.2) < 1e-9
    assert pg["execution"]["most_material_pair"]["material"] is True
    pvar = {v["field_name"]: v for v in pg["variants"]}
    assert pvar["Revenue"]["execution"]["value"] == REDACTED
    assert pvar["RevenueV2"]["execution"]["value"] == REDACTED
    assert pvar["RevenueV2"]["execution"]["material"] is True


# -- R5: the execution figures reach the web app (and stay redacted) ----------

def _findings_with_execution():
    """A minimal full findings dict carrying the seeded VDS execution rows, the
    shape emit hands to the web app."""
    store, _summary = _material_store()
    dm = _definition_multiplicity(store, "r")
    return {"meta": {"framing": "full"}, "facets": [], "domains": [],
            "flags": [], "coverage": [],
            "findings": {"definition_multiplicity": dm,
                         "security_exposure": {}, "retirement": {}}}


def _embedded_payload(html):
    m = re.search(
        r'<script id="findings-data" type="application/json">(.*?)</script>',
        html, re.DOTALL)
    assert m, "no embedded findings payload"
    return json.loads(m.group(1))


def _exec_group(payload):
    return payload["findings"]["definition_multiplicity"]["groups"][0]


def test_execution_surfaces_in_working_webapp_payload():
    # Read the payload out of the actual rendered HTML, so this proves the figure
    # travels all the way into the self-contained document.
    html = render_html(mark_working(_findings_with_execution()))
    group = _exec_group(_embedded_payload(html))
    assert group["execution"]["most_material_pair"]["variant_field"] == "RevenueV2"
    assert group["execution"]["most_material_pair"]["reference_value"] == 1000.0
    var = {v["field_name"]: v for v in group["variants"]}
    assert var["RevenueV2"]["execution"]["value"] == 1200.0


def test_execution_redacted_in_presentation_webapp():
    html = render_html(redact(_findings_with_execution()))
    group = _exec_group(_embedded_payload(html))
    pair = group["execution"]["most_material_pair"]
    # Raw executed values are gone from the embedded payload; the safe diff
    # figures remain so the material gap is still shown.
    assert pair["reference_value"] == REDACTED
    assert pair["variant_value"] == REDACTED
    assert pair["material"] is True
    assert abs(pair["rel_diff"] - 0.2) < 1e-9
    var = {v["field_name"]: v for v in group["variants"]}
    assert var["Revenue"]["execution"]["value"] == REDACTED
    assert var["RevenueV2"]["execution"]["value"] == REDACTED
