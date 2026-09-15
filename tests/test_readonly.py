"""R1 acceptance: read-only is enforced in code, and secrets never load.

Three gates, defense-in-depth, each asserted here with no network:

  * Gate A -- every query in the fixed set is a read (`assert_read_only`), and a
    mutation document is refused.
  * Gate B -- every registered REST resource is a GET, and a write verb cannot
    even be registered.
  * Gate C -- the transport guard raises on a non-allowlisted POST and on a
    mutation body reaching the Metadata endpoint, while a real query passes.

Plus the secret-hygiene floor: `assert_no_secrets_in_config` hard-aborts on a
planted secret and never echoes its value, and `LiveClient.close()` signs out
and nulls the token.
"""

import json
import os

import httpx
import pytest

from estate_scan import queries
from estate_scan.clients import rest_resources
from estate_scan.clients.auth import Credentials, build_session
from estate_scan.clients.live import LiveClient
from estate_scan.clients.rest_resources import RestResource
from estate_scan.readonly import (
    ReadOnlyViolation,
    assert_graphql_read_only,
    graphql_operations,
)
from estate_scan.security import ReadOnlyGuard, assert_no_secrets_in_config

from tests.transport import FixtureTransport

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _estate(profile="median"):
    with open(os.path.join(FIXTURES, profile, "estate.json")) as fh:
        return json.load(fh)


def _config(estate):
    return {"host": "https://fixture.online.tableau.com",
            "deployment_type": estate.get("meta", {}).get("deployment_type", "cloud"),
            "site_content_url": ""}


# -- Gate A: GraphQL by-name + operation check -------------------------------

def test_every_manifest_query_is_read_only():
    manifest = queries.load_manifest()
    names = sorted(manifest.get("graphql", {}))
    assert names, "manifest has no queries"
    for name in names:
        # Loads the checksum-verified text and asserts every operation is a query.
        queries.assert_read_only(name)


def test_mutation_document_is_refused():
    with pytest.raises(ReadOnlyViolation):
        assert_graphql_read_only("mutation Evil { deleteWorkbook(id: 1) }",
                                 label="planted")


def test_empty_document_fails_closed():
    # An unparseable/empty document is refused, never waved through.
    with pytest.raises(ReadOnlyViolation):
        assert_graphql_read_only("", label="empty")


def test_description_text_does_not_cause_a_false_rejection():
    # The word "mutation" inside a comment or a string literal must not be
    # misread as a write operation (stripping keeps the fixed query set usable).
    doc = ('# this query is not a mutation\n'
           'query projects { name description }')
    ops = graphql_operations(doc)
    assert "mutation" not in ops and "subscription" not in ops
    assert_graphql_read_only(doc)  # must not raise


# -- Gate B: REST verb/resource allowlist ------------------------------------

def test_every_registered_rest_resource_is_get():
    assert rest_resources.names(), "registry is empty"
    for name in rest_resources.names():
        assert rest_resources.get(name).method == "GET", name


def test_registering_a_write_verb_is_refused():
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(ReadOnlyViolation):
            RestResource("evil", verb, "/api/{version}/x", "x")


def test_unregistered_resource_raises():
    assert not rest_resources.is_registered("usage_events")
    with pytest.raises(KeyError):
        rest_resources.get("usage_events")


# -- Gate C: the transport guard ---------------------------------------------

def _guarded_client(handler):
    guarded = ReadOnlyGuard(httpx.MockTransport(handler))
    return httpx.Client(base_url="https://fixture.online.tableau.com",
                        transport=guarded)


def test_guard_allows_get_and_read_posts():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"ok": True})

    client = _guarded_client(handler)
    # GET is a read.
    assert client.get("/api/3.24/sites/s/workbooks").status_code == 200
    # A query POST to the Metadata endpoint is allowed.
    assert client.post("/api/metadata/graphql",
                       json={"query": "query projects { p }"}).status_code == 200
    client.close()
    assert ("GET", "/api/3.24/sites/s/workbooks") in seen


def test_guard_refuses_non_allowlisted_post():
    client = _guarded_client(lambda r: httpx.Response(200))
    with pytest.raises(ReadOnlyViolation):
        client.post("/api/3.24/sites/s/workbooks", json={"name": "x"})
    client.close()


def test_guard_refuses_write_verbs():
    client = _guarded_client(lambda r: httpx.Response(200))
    for verb in ("PUT", "PATCH", "DELETE"):
        with pytest.raises(ReadOnlyViolation):
            client.request(verb, "/api/3.24/sites/s/workbooks/1")
    client.close()


def test_guard_refuses_mutation_body_to_metadata():
    client = _guarded_client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ReadOnlyViolation):
        client.post("/api/metadata/graphql",
                    json={"query": "mutation M { deleteWorkbook(id: 1) }"})
    client.close()


def test_guard_refuses_write_shaped_vds_body():
    client = _guarded_client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ReadOnlyViolation):
        client.post("/api/v1/vizql-data-service/query-datasource",
                    json={"datasource": {"luid": "x"}, "publish": {"name": "y"}})
    client.close()


def test_guard_wraps_whatever_transport_it_is_given():
    # The seam that makes the test meaningful: build_session wraps the injected
    # MockTransport in the shipping guard.
    ft = FixtureTransport(_estate())
    client = build_session("https://fixture.online.tableau.com",
                           transport=ft.transport)
    assert isinstance(client._transport, ReadOnlyGuard)
    client.close()


# -- secret hygiene ----------------------------------------------------------

def test_clean_config_passes():
    assert_no_secrets_in_config({
        "host": "https://x.online.tableau.com",
        "deployment_type": "cloud",
        "pat_name": "estate-scan-readonly",   # the NAME is not a secret
        "site_content_url": "",
        "core_metrics": ["Revenue"],
    })


def test_forbidden_key_aborts_and_never_echoes_value():
    secret = "AbcdEFGH1234ijklMNOP5678qrstUVWX"
    with pytest.raises(SystemExit) as exc:
        assert_no_secrets_in_config({"host": "https://x", "pat_secret": secret})
    assert secret not in str(exc.value)


def test_secret_shaped_value_aborts_even_under_innocuous_key():
    secret = "Za9Xb8Yc7Wd6Ve5Uf4Tg3Sh2Ri1Qj0Pk9Lm8Nn7"  # 40-char mixed-class token
    with pytest.raises(SystemExit) as exc:
        assert_no_secrets_in_config({"host": "https://x", "note": secret})
    assert secret not in str(exc.value)


def test_nested_secret_is_found():
    with pytest.raises(SystemExit):
        assert_no_secrets_in_config(
            {"host": "https://x", "auth": {"token": "whatever"}})


# -- close() signs out and nulls the token -----------------------------------

def test_close_signs_out_and_nulls_token():
    estate = _estate()
    ft = FixtureTransport(estate)
    client = LiveClient(_config(estate), transport=ft.transport,
                        credentials=Credentials("pat", "secret", "env"))
    client.connect()
    assert client._token is not None
    client.close()
    assert client._token is None
    assert any(m == "POST" and p.endswith("/auth/signout")
               for (m, p) in ft.requests), "signout was not issued"


def test_close_is_idempotent():
    estate = _estate()
    ft = FixtureTransport(estate)
    client = LiveClient(_config(estate), transport=ft.transport,
                        credentials=Credentials("pat", "secret", "env"))
    client.connect()
    client.close()
    client.close()  # must not raise
