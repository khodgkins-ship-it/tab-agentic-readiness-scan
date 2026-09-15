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
from estate_scan.report.redact import REDACTED, redact
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
        store.save_metric_variant(run_id, "g1", fid, "h_" + fid, rank, views,
                                  wbs, dom)
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
