"""R1 acceptance: the live client, driven entirely offline through a mock.

Everything here runs against `FixtureTransport` (a mocked httpx transport), so
there is no network and no credentials. The suite covers the acceptance list:
sign-in, API-version negotiation, pagination, session-expiry surfaced (not
swallowed), partial-response subdivision, proactive PAT refresh on elapsed time,
Metadata-disabled abort, the Cloud/Server owner difference, and -- the load-
bearing one -- that `LiveClient` over the fixture transport extracts the *same*
estate as `FixtureClient` (the backend-agnostic invariant).
"""

import copy
import json
import os

import pytest

from estate_scan.clients.auth import AuthError, Credentials
from estate_scan.clients.fixture import FixtureClient
from estate_scan.clients.live import LiveClient
from estate_scan.extract.runner import ExtractRunner
from estate_scan.store import Store

from tests.transport import FixtureTransport

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PROFILES = ["median", "small", "hostile"]


def _estate(profile):
    with open(os.path.join(FIXTURES, profile, "estate.json")) as fh:
        return json.load(fh)


def _config(estate, **overrides):
    cfg = {"host": "https://fixture.online.tableau.com",
           "deployment_type": estate.get("meta", {}).get("deployment_type", "cloud"),
           "site_content_url": ""}
    cfg.update(overrides)
    return cfg


def _live(estate, transport, **cfg_overrides):
    return LiveClient(_config(estate, **cfg_overrides), transport=transport,
                      credentials=Credentials("pat", "secret", "env"))


def _run_fixture(estate, run_id="rf"):
    store = Store.open(":memory:")
    ExtractRunner(FixtureClient(estate), store, run_id).run()
    return store


def _run_live(estate, run_id="rl", partial_over=None):
    ft = FixtureTransport(estate, partial_over=partial_over)
    client = _live(estate, ft.transport)
    client.connect()  # run() reads site_id at the top, so connect first
    store = Store.open(":memory:")
    runner = ExtractRunner(client, store, run_id)
    runner.run()
    return store, ft, runner


# -- the backend-agnostic invariant ------------------------------------------

@pytest.mark.parametrize("profile", PROFILES)
def test_live_extracts_same_estate_as_fixture(profile):
    estate = _estate(profile)
    fx = _run_fixture(estate)
    lv, _, _ = _run_live(estate)
    for table in ("projects", "datasources", "workbooks", "fields"):
        assert lv.count(table, "rl") == fx.count(table, "rf"), \
            "%s count differs between backends" % table
    assert lv.datasource_ids("rl") == fx.datasource_ids("rf")


@pytest.mark.parametrize("profile", PROFILES)
def test_live_counts_match_manifest(profile):
    with open(os.path.join(FIXTURES, profile, "manifest.json")) as fh:
        counts = json.load(fh)["counts"]
    lv, _, _ = _run_live(_estate(profile))
    assert lv.count("projects", "rl") == counts["projects"]
    assert lv.count("datasources", "rl") == counts["datasources"]
    assert lv.count("workbooks", "rl") == counts["workbooks"]
    assert lv.count("fields", "rl") == counts["fields_total"]


# -- sign-in and version negotiation -----------------------------------------

def test_negotiates_server_api_version():
    estate = _estate("median")
    ft = FixtureTransport(estate, api_version="3.16")  # an older Server version
    client = _live(estate, ft.transport)
    client.connect()
    assert client._api_version == "3.16"
    assert ("GET", "/api/serverinfo") in ft.requests
    client.close()


def test_pinned_version_skips_negotiation():
    estate = _estate("median")
    ft = FixtureTransport(estate, api_version="3.16")
    client = _live(estate, ft.transport, api_version="3.99")
    client.connect()
    assert client._api_version == "3.99"
    assert ("GET", "/api/serverinfo") not in ft.requests
    client.close()


def test_signin_records_site_identity():
    estate = _estate("median")
    ft = FixtureTransport(estate)
    client = _live(estate, ft.transport)
    client.connect()
    assert client.site_id == ft.site_id
    assert client.site_name == ft.site_name
    assert client._token == "tok-1"
    client.close()


def test_signin_failure_raises():
    estate = _estate("median")
    ft = FixtureTransport(estate, signin_status=401)
    client = _live(estate, ft.transport)
    with pytest.raises(AuthError):
        client.connect()


def test_connect_is_idempotent():
    estate = _estate("median")
    ft = FixtureTransport(estate)
    client = _live(estate, ft.transport)
    client.connect()
    client.connect()  # second call is a no-op; no second sign-in
    assert ft.signin_count == 1
    client.close()


# -- capability probing ------------------------------------------------------

def test_metadata_disabled_aborts_with_operator_guidance():
    estate = _estate("median")
    ft = FixtureTransport(estate, metadata_available=False)
    client = _live(estate, ft.transport)
    client.connect()
    with pytest.raises(SystemExit) as exc:
        client.detect_capabilities()
    assert "Metadata API" in str(exc.value)
    client.close()


def test_capabilities_reflect_rest_probe_failure():
    # The fixture serves REST probes as 403, so rest_jobs/rest_tasks are False --
    # exactly as FixtureClient reports.
    estate = _estate("median")
    ft = FixtureTransport(estate)
    client = _live(estate, ft.transport)
    client.connect()
    caps = client.detect_capabilities()
    assert caps["metadata_api"] is True
    assert caps["rest_jobs"] is False
    assert caps["rest_tasks"] is False
    client.close()


# -- session expiry and refresh ----------------------------------------------

def test_session_expiry_is_surfaced_not_swallowed():
    estate = _estate("median")
    ft = FixtureTransport(estate, graphql_status=401)
    client = _live(estate, ft.transport)
    client.connect()  # sign-in succeeds; the query then 401s
    res = client.graphql("projects")
    assert res.ok is False
    assert res.error == "SESSION_EXPIRED"
    client.close()


class _Clock(object):
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_proactive_pat_refresh_on_elapsed_time():
    estate = _estate("median")
    ft = FixtureTransport(estate)
    clock = _Clock()
    client = LiveClient(_config(estate, session_refresh_seconds=100),
                        transport=ft.transport, clock=clock,
                        credentials=Credentials("pat", "secret", "env"))
    client.connect()
    assert client._token == "tok-1"
    clock.advance(150)  # past the refresh window
    client.graphql("projects")  # triggers a proactive re-sign-in
    assert ft.signin_count == 2
    assert client._token == "tok-2"
    assert any(p.endswith("/auth/signout") for (_, p) in ft.requests)
    client.close()


def test_no_refresh_before_the_window():
    estate = _estate("median")
    ft = FixtureTransport(estate)
    clock = _Clock()
    client = LiveClient(_config(estate, session_refresh_seconds=3000),
                        transport=ft.transport, clock=clock,
                        credentials=Credentials("pat", "secret", "env"))
    client.connect()
    clock.advance(10)
    client.graphql("projects")
    assert ft.signin_count == 1  # still the original session
    client.close()


# -- partial-response subdivision --------------------------------------------

def test_partial_response_subdivides_over_the_wire():
    estate = _estate("median")
    # Force any workbooks page over 50 nodes to come back as a NODE_LIMIT partial.
    lv, ft, runner = _run_live(estate, partial_over={"workbooks": 50})
    # The runner must have subdivided rather than accepted truncated data...
    assert runner.subdivision_events, "no subdivision occurred"
    assert all(sk.startswith("workbooks") for (sk, _, _) in runner.subdivision_events)
    # ...and still extracted every workbook.
    fx = _run_fixture(estate)
    assert lv.count("workbooks", "rl") == fx.count("workbooks", "rf")


# -- usage_events differs by design in R1 ------------------------------------

def test_usage_events_fails_on_live_but_succeeds_on_fixture():
    estate = _estate("median")
    fx = _run_fixture(estate)
    lv, _, _ = _run_live(estate)
    fx_cov = {r["measure"]: r["status"] for r in fx.coverage("rf")}
    lv_cov = {r["measure"]: r["status"] for r in lv.coverage("rl")}
    assert fx_cov["usage_events"] == "ok"
    # Live has no R1 source for usage_events (VDS/repository is R2/R3): honest
    # failure, never a clean empty result.
    assert lv_cov["usage_events"] == "failed"


# -- Cloud/Server owner difference recorded as coverage ----------------------

def test_owner_gap_recorded_as_partial_coverage():
    # Simulate a Server site that does not expose workbook owners: strip them and
    # confirm the client records the attribution gap rather than reading clean.
    estate = copy.deepcopy(_estate("median"))
    for wb in estate.get("workbooks", []):
        wb["owner"] = {}
    lv, _, _ = _run_live(estate)
    cov = {r["measure"]: r["status"] for r in lv.coverage("rl")}
    assert cov.get("owner_attribution") == "partial"


def test_no_owner_gap_when_owners_present():
    # The fixture backend never emits this note; the live client only emits it
    # when it actually observes missing owners.
    estate = _estate("median")
    lv, _, _ = _run_live(estate)
    cov = {r["measure"] for r in lv.coverage("rl")}
    assert "owner_attribution" not in cov
