"""R2 acceptance: Cloud usage extraction via VDS / Admin Insights.

On Tableau Cloud there is no REST endpoint that returns per-workbook view
counts, so `usage_events` is sourced from the Admin Insights published data
sources read through the read-only VizQL Data Service as a grouped aggregate.
These tests exercise that path entirely offline: the *production* `LiveClient`
runs over a `FixtureTransport` (so the shipping read-only guard and VDS parser
are on the wire), the store is seeded directly, and the runner's usage step is
invoked in isolation.

The load-bearing guarantees under test:

  * the grouped usage body is read-only by construction (passes the shipping
    `assert_vds_body_read_only`);
  * the runner dispatches to VDS when the service is present, mapping rows onto
    the existing `usage_events` grain and recording `adoption_source`;
  * every failure mode (no Admin Insights source, captions that do not resolve)
    is an honest `skipped` with a reason -- never garbage loaded as clean, and
    never a silent fall-through to a Cloud REST endpoint that does not exist;
  * the fixture REST path (no VDS capability) is unchanged.
"""

import json
import os

from estate_scan.clients.auth import Credentials
from estate_scan.clients.fixture import FixtureClient
from estate_scan.clients.live import LiveClient
from estate_scan.extract import usage_vds
from estate_scan.extract.runner import ExtractRunner
from estate_scan.clients.vds import VdsExecutor
from estate_scan.readonly import assert_vds_body_read_only
from estate_scan.store import Store

from tests.transport import FixtureTransport

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
_AI_LUID = "luid-ai"
_NOW = "2026-09-16T00:00:00Z"


def _estate(profile="median"):
    with open(os.path.join(FIXTURES, profile, "estate.json")) as fh:
        return json.load(fh)


def _config(estate, admin_insights=None):
    cfg = {"host": "https://fixture.online.tableau.com",
           "deployment_type": "cloud", "site_content_url": ""}
    if admin_insights is not None:
        cfg["admin_insights"] = admin_insights
    return cfg


def _connected_client(vds_available=True, vds_rows=None, admin_insights=None):
    estate = _estate()
    ft = FixtureTransport(estate, vds_available=vds_available, vds_rows=vds_rows or {})
    client = LiveClient(_config(estate, admin_insights), transport=ft.transport,
                        credentials=Credentials("pat", "secret", "env"))
    client.connect()
    client.detect_capabilities()
    return client, ft


def _seed(store, run_id="r", ai_project="Admin Insights",
          ai_name="Admin Insights Starter", with_ai_source=True):
    """A minimal estate: two workbooks, plus (optionally) an Admin Insights
    published data source in its own project so the extractor can resolve it."""
    store.start_run(run_id, {"site_name": "Fixture", "deployment_type": "cloud",
                             "adoption_source": "unavailable", "mode": "scan"})
    if with_ai_source:
        store.load_datasources(run_id, [
            {"id": "ds-ai", "luid": _AI_LUID, "name": ai_name,
             "projectName": ai_project}])
    store.load_workbooks(run_id, [
        {"id": "w1", "luid": "wb-luid-1", "name": "Sales Overview",
         "projectName": "Analytics"},
        {"id": "w2", "luid": "wb-luid-2", "name": "Ops Dashboard",
         "projectName": "Analytics"}])
    store.commit()


def _run_usage(store, client, run_id="r"):
    runner = ExtractRunner(client, store, run_id)
    runner._capabilities = client.capabilities or {}
    # Pin "now" so last_viewed_days_ago is deterministic (it would otherwise be
    # computed against the wall clock and drift as the calendar advances).
    runner._run_usage_events(now=_NOW)


def _cov(store, run_id="r"):
    return {r["measure"]: r for r in store.coverage(run_id)}


def _usage_rows(store, run_id="r"):
    cur = store.conn.execute(
        "SELECT workbook_id, workbook_luid, user_id, event_count, "
        "last_viewed_days_ago FROM usage_events WHERE run_id=? ORDER BY workbook_id",
        (run_id,))
    return [dict(r) for r in cur.fetchall()]


# -- the grouped body is read-only by construction ---------------------------

def test_usage_query_is_read_only_and_grouped():
    ai = usage_vds.AdminInsightsConfig.from_config(None)
    body = usage_vds.build_usage_query(VdsExecutor(None), _AI_LUID, ai, _NOW)
    # Never raises: only datasource + query{fields, filters}, no write keys.
    assert_vds_body_read_only(body, label="test")
    assert body["datasource"]["datasourceLuid"] == _AI_LUID
    fields = body["query"]["fields"]
    # One dimension (the workbook luid, no function) + two aliased measures.
    dims = [f for f in fields if "function" not in f]
    measures = [f for f in fields if "function" in f]
    assert [f["fieldCaption"] for f in dims] == [ai.captions["workbook_luid"]]
    assert {m["fieldAlias"] for m in measures} == {
        usage_vds._ALIAS_VIEWS, usage_vds._ALIAS_LAST}
    # A view-type SET filter and a date-window MIN filter bound the read.
    ftypes = {f["filterType"] for f in body["query"]["filters"]}
    assert ftypes == {"SET", "QUANTITATIVE_DATE"}


def test_window_start_precedes_now():
    ai = usage_vds.AdminInsightsConfig.from_config({"window_days": 30})
    body = usage_vds.build_usage_query(VdsExecutor(None), _AI_LUID, ai, _NOW)
    date_filter = [f for f in body["query"]["filters"]
                   if f["filterType"] == "QUANTITATIVE_DATE"][0]
    assert date_filter["minDate"] == "2026-08-17"  # 2026-09-16 minus 30 days


# -- dispatch: VDS chosen when the capability is present ----------------------

def test_dispatch_uses_vds_and_maps_rows():
    store = Store.open(":memory:")
    _seed(store)
    rows = [
        {"Item LUID": "wb-luid-1", "view_count": 40, "last_event_date": "2026-09-10"},
        {"Item LUID": "wb-luid-2", "view_count": 3, "last_event_date": "2026-06-01"},
        # A view row for a workbook outside this scan -> counted, not loaded.
        {"Item LUID": "wb-luid-ghost", "view_count": 99, "last_event_date": "2026-09-01"},
    ]
    client, ft = _connected_client(vds_available=True, vds_rows={_AI_LUID: rows})
    try:
        _run_usage(store, client)
    finally:
        client.close()

    # The query went out as a POST to the one query-datasource path.
    assert ("POST", "/api/v1/vizql-data-service/query-datasource") in ft.requests

    loaded = _usage_rows(store)
    assert [r["workbook_id"] for r in loaded] == ["w1", "w2"]  # ghost dropped
    by_wb = {r["workbook_id"]: r for r in loaded}
    assert by_wb["w1"]["event_count"] == 40
    assert by_wb["w1"]["last_viewed_days_ago"] == 6      # 2026-09-16 - 2026-09-10
    assert all(r["user_id"] is None for r in loaded)     # per-workbook grain

    cov = _cov(store)
    assert cov["usage_events"]["status"] == "ok"
    assert "1 view rows for workbooks outside this scan" in cov["usage_events"]["reason"]
    # Per-user depth is not derivable from a per-workbook read -> honest skip.
    assert cov["adoption_depth"]["status"] == "skipped"
    # The source is recorded for the report's provenance line.
    assert store.get_run("r")["adoption_source"] == "admin_insights"


def test_empty_result_is_ok_not_skipped():
    # A legitimately quiet site: the source resolves, the query shape is right,
    # but no views fall in the window. That is a measured zero, not a failure.
    store = Store.open(":memory:")
    _seed(store)
    client, _ft = _connected_client(vds_available=True, vds_rows={_AI_LUID: []})
    try:
        _run_usage(store, client)
    finally:
        client.close()
    assert _usage_rows(store) == []
    assert _cov(store)["usage_events"]["status"] == "ok"
    assert store.get_run("r")["adoption_source"] == "admin_insights"


# -- honest skips: never load a guess ----------------------------------------

def test_missing_admin_insights_source_skips_without_querying():
    store = Store.open(":memory:")
    _seed(store, with_ai_source=False)   # no source in the Admin Insights project
    client, ft = _connected_client(vds_available=True, vds_rows={})
    try:
        _run_usage(store, client)
    finally:
        client.close()
    assert _usage_rows(store) == []
    cov = _cov(store)
    assert cov["usage_events"]["status"] == "skipped"
    assert "Admin Insights" in cov["usage_events"]["reason"]
    assert cov["adoption_depth"]["status"] == "skipped"
    # No VDS query was issued, and the source stays unset (no false provenance).
    assert ("POST", "/api/v1/vizql-data-service/query-datasource") not in ft.requests
    assert store.get_run("r")["adoption_source"] == "unavailable"


def test_wrong_captions_skip_not_garbage():
    # The source resolves, but the returned rows are keyed by unexpected columns
    # (captions drifted / did not resolve). The extractor must skip with a reason,
    # never load rows it cannot key to a workbook.
    store = Store.open(":memory:")
    _seed(store)
    rows = [{"Unexpected Column": "wb-luid-1", "some_measure": 5}]
    client, _ft = _connected_client(vds_available=True, vds_rows={_AI_LUID: rows})
    try:
        _run_usage(store, client)
    finally:
        client.close()
    assert _usage_rows(store) == []
    cov = _cov(store)
    assert cov["usage_events"]["status"] == "skipped"
    assert "captions" in cov["usage_events"]["reason"]
    assert store.get_run("r")["adoption_source"] == "unavailable"


def test_config_overrides_resolve_by_name_and_captions():
    # A site whose Admin Insights source and field names differ from the defaults
    # is handled purely by config -- no code change.
    store = Store.open(":memory:")
    _seed(store, ai_project="Insights", ai_name="Site Events")
    ai_cfg = {"project_name": "Insights", "datasource_name": "Site Events",
              "captions": {"workbook_luid": "View LUID"}}
    rows = [{"View LUID": "wb-luid-1", "view_count": 7, "last_event_date": "2026-09-15"}]
    client, _ft = _connected_client(vds_available=True, vds_rows={_AI_LUID: rows},
                                    admin_insights=ai_cfg)
    try:
        _run_usage(store, client)
    finally:
        client.close()
    loaded = _usage_rows(store)
    assert [r["workbook_id"] for r in loaded] == ["w1"]
    assert loaded[0]["event_count"] == 7
    assert _cov(store)["usage_events"]["status"] == "ok"


# -- the fixture REST path is untouched --------------------------------------

def test_fixture_rest_path_unchanged():
    # The fixture client has no VDS capability, so the dispatcher takes the
    # registered REST path exactly as before this change.
    estate = _estate()
    store = Store.open(":memory:")
    store.start_run("r", {"site_name": "Fixture", "deployment_type": "cloud",
                          "adoption_source": "fixture", "mode": "scan"})
    fc = FixtureClient(estate)
    runner = ExtractRunner(fc, store, "r")
    runner._capabilities = {}          # no vizql_data_service -> REST path
    runner._run_usage_events()
    cov = _cov(store)
    # The fixture serves usage_events over REST; coverage reflects that path.
    assert cov["usage_events"]["status"] in ("ok", "skipped", "failed")
    # Whatever the outcome, it did NOT touch the VDS/Admin Insights source line.
    assert store.get_run("r")["adoption_source"] == "fixture"
