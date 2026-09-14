"""M1 acceptance: the fixtures load through `clients/fixture.py`, and the
expected-results manifest is the assertion target.

These tests prove three things the rest of the build leans on:

  * Every fixture round-trips through the same `EstateClient` interface the
    live clients will implement, with working cursor pagination.
  * The counts the generator *measured* into each manifest are exactly what the
    client replays -- so the manifest is a trustworthy oracle for M2-M7.
  * No `_`-prefixed ground-truth key ever reaches a response, so the derivation
    pipeline must rediscover concepts/dominance/depth from names and formulas
    rather than reading the answer key.

Plus the partial-response hook that tests/test_partial.py (M2) will drive.
"""

import json
import os

import pytest

from estate_scan import queries
from estate_scan.clients.fixture import FixtureClient

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
PROFILES = ["median", "small", "hostile"]


def _load(profile):
    base = os.path.join(FIXTURES_DIR, profile)
    client = FixtureClient.from_path(os.path.join(base, "estate.json"))
    with open(os.path.join(base, "manifest.json")) as fh:
        manifest = json.load(fh)
    return client, manifest


def _walk(client, query_name, conn_key, page_size, **base_vars):
    """Drive a *Connection query to exhaustion and return every node.

    Also asserts each page is `ok` and that pagination actually terminates.
    """
    nodes = []
    after = None
    seen_cursors = set()
    for _ in range(100000):  # hard stop guards against a cursor that never ends
        v = dict(base_vars)
        v["first"] = page_size
        if after is not None:
            v["after"] = after
        res = client.graphql(query_name, v)
        assert res.ok, "%s page failed: %r" % (query_name, res)
        assert not res.partial, "%s unexpectedly partial: %r" % (query_name, res)
        conn = res.data[conn_key]
        nodes.extend(conn["nodes"])
        page_info = conn["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]
        assert after not in seen_cursors, "cursor repeated: %r" % after
        seen_cursors.add(after)
    return nodes


def _is_ground_truth_key(key):
    # Ground-truth keys are single-underscore prefixed (`_concept`,
    # `_view_count`). GraphQL's own `__typename` is dunder and legitimate.
    return isinstance(key, str) and key.startswith("_") and not key.startswith("__")


def _assert_no_ground_truth(obj, path="root"):
    """No single-underscore ground-truth key may appear in a returned envelope."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            assert not _is_ground_truth_key(key), \
                "ground-truth key %r leaked at %s" % (key, path)
            _assert_no_ground_truth(val, path + "." + str(key))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_ground_truth(item, "%s[%d]" % (path, i))


# ---------------------------------------------------------------------------
# Counts: the manifest is the oracle.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile", PROFILES)
def test_top_level_counts_match_manifest(profile):
    client, manifest = _load(profile)
    counts = manifest["counts"]

    projects = _walk(client, "projects", "projectsConnection", 1000)
    datasources = _walk(client, "published_datasources",
                        "publishedDatasourcesConnection", 200)
    workbooks = _walk(client, "workbooks", "workbooksConnection", 200)

    assert len(projects) == counts["projects"]
    assert len(datasources) == counts["datasources"]
    assert len(workbooks) == counts["workbooks"]


@pytest.mark.parametrize("profile", PROFILES)
def test_field_counts_match_manifest(profile):
    client, manifest = _load(profile)
    counts = manifest["counts"]

    datasources = _walk(client, "published_datasources",
                        "publishedDatasourcesConnection", 200)

    # fieldsConnection.totalCount summed over sources is the total field count.
    total_from_ds = sum(d["fieldsConnection"]["totalCount"] for d in datasources)
    assert total_from_ds == counts["fields_total"]

    # Walk each source's fields and count them independently, plus calc fields.
    walked_total = 0
    calc_total = 0
    for d in datasources:
        fields = _walk_fields(client, d["id"])
        walked_total += len(fields)
        calc_total += sum(1 for f in fields
                          if f.get("__typename") == "CalculatedField")

    assert walked_total == counts["fields_total"]
    assert calc_total == counts["calculated_fields"]


def _walk_fields(client, ds_id, page_size=200):
    """Walk the field connection nested under a single published data source."""
    fields = []
    after = None
    for _ in range(100000):
        v = {"dsId": ds_id, "first": page_size}
        if after is not None:
            v["after"] = after
        res = client.graphql("datasource_fields", v)
        assert res.ok and not res.partial
        nodes = res.data["publishedDatasourcesConnection"]["nodes"]
        if not nodes:
            break
        fconn = nodes[0]["fieldsConnection"]
        fields.extend(fconn["nodes"])
        page_info = fconn["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]
    return fields


# ---------------------------------------------------------------------------
# No answer key leaks into responses.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile", PROFILES)
def test_no_ground_truth_keys_leak(profile):
    client, _ = _load(profile)

    for query, conn, size in [
        ("projects", "projectsConnection", 1000),
        ("published_datasources", "publishedDatasourcesConnection", 200),
        ("workbooks", "workbooksConnection", 200),
    ]:
        res = client.graphql(query, {"first": size})
        _assert_no_ground_truth(res.data)

    # Field envelopes carry the formulas -- the most likely place for a leak.
    ds = client.graphql("published_datasources",
                        {"first": 200}).data["publishedDatasourcesConnection"]["nodes"]
    for d in ds[:25]:
        res = client.graphql("datasource_fields", {"dsId": d["id"], "first": 200})
        _assert_no_ground_truth(res.data)


@pytest.mark.parametrize("profile", PROFILES)
def test_calculated_fields_expose_formula_columns_do_not(profile):
    """Sanity on projection: a calc field carries `formula`; a column field
    never does (its fragment doesn't select one)."""
    client, _ = _load(profile)
    ds = client.graphql("published_datasources",
                        {"first": 200}).data["publishedDatasourcesConnection"]["nodes"]
    saw_calc = False
    for d in ds:
        for f in _walk_fields(client, d["id"]):
            if f["__typename"] == "CalculatedField":
                assert "formula" in f
                saw_calc = True
            elif f["__typename"] == "ColumnField":
                assert "formula" not in f
    if client.run_config()["core_metrics"]:
        assert saw_calc, "expected at least one calculated field in %s" % profile


@pytest.mark.parametrize("profile", PROFILES)
def test_field_usage_linkage_joins_to_events(profile):
    """Calc fields expose referencedBySheets -> workbook, and every referenced
    workbook is a real workbook present in usage_events. This is the linkage
    M4 ranks variants on; the hidden `_view_count` is NOT exposed, so ranking
    must recompute views from this join."""
    client, _ = _load(profile)

    events = client.rest("usage_events").items
    known_wb = set()
    for e in events:
        for k in (e.get("workbook_luid"), e.get("workbook_id")):
            if k:
                known_wb.add(k)

    ds = client.graphql("published_datasources",
                        {"first": 200}).data["publishedDatasourcesConnection"]["nodes"]
    fields_with_usage = 0
    for d in ds:
        for f in _walk_fields(client, d["id"]):
            if f["__typename"] != "CalculatedField":
                continue
            for s in f.get("sheetsUsedIn", []):
                wb = s.get("workbook") or {}
                luid = wb.get("luid")
                assert luid, "sheetsUsedIn entry missing workbook luid: %r" % s
                assert luid in known_wb, "usage points at unknown workbook %r" % luid
            if f.get("sheetsUsedIn"):
                fields_with_usage += 1

    if client.run_config()["core_metrics"]:
        assert fields_with_usage > 0, "expected metric variants to carry usage"


# ---------------------------------------------------------------------------
# Pagination is real: smaller pages yield the same nodes.
# ---------------------------------------------------------------------------

def test_pagination_is_stable_across_page_sizes():
    client, manifest = _load("median")
    big = _walk(client, "workbooks", "workbooksConnection", 1000)
    small = _walk(client, "workbooks", "workbooksConnection", 37)  # awkward size
    assert len(big) == len(small) == manifest["counts"]["workbooks"]
    assert [w["id"] for w in big] == [w["id"] for w in small]


# ---------------------------------------------------------------------------
# REST usage events replay.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile", PROFILES)
def test_usage_events_replay(profile):
    client, _ = _load(profile)
    res = client.rest("usage_events")
    assert res.ok
    assert res.total_available == len(res.items)
    _assert_no_ground_truth({"items": res.items})


# ---------------------------------------------------------------------------
# Partial-response hook (drives M2's subdivision test).
# ---------------------------------------------------------------------------

def test_partial_hook_forces_node_limit():
    base = os.path.join(FIXTURES_DIR, "median", "estate.json")
    client = FixtureClient.from_path(base, partial_over={"workbooks": 50})

    # Asking for more than the threshold trips a NODE_LIMIT_EXCEEDED partial.
    res = client.graphql("workbooks", {"first": 200})
    assert res.ok and res.partial
    assert "NODE_LIMIT_EXCEEDED" in res.warnings

    # Asking within the threshold returns complete, trustworthy data.
    res = client.graphql("workbooks", {"first": 50})
    assert res.ok and not res.partial
    assert res.warnings == []


def test_partial_hook_off_by_default():
    client, _ = _load("median")
    res = client.graphql("workbooks", {"first": 1000})
    assert res.ok and not res.partial


# ---------------------------------------------------------------------------
# Query set version pins the fixtures to the versioned query catalog.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile", PROFILES)
def test_manifest_query_set_version_matches_catalog(profile):
    _, manifest = _load(profile)
    assert manifest["query_set_version"] == queries.query_set_version()


def test_versioned_queries_verify():
    # Every checksum in queries/manifest.json matches its .graphql file.
    queries.verify_all()
