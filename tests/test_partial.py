"""M2 deliverable: partial responses subdivide, never get accepted truncated.

GraphQL returns partial data alongside a node-limit error when a page is too
large. The runner must subdivide the shard (halve the page size) and retry the
same cursor, and must NEVER advance past a partial page. Accepting truncated
data silently is the tool's most dangerous failure. These tests force the
condition through the fixture's `partial_over` hook and assert the behaviour.
"""

import json
import os

from estate_scan.clients.fixture import FixtureClient
from estate_scan.extract.runner import ExtractRunner
from estate_scan.store import Store

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
MEDIAN = os.path.join(FIXTURES, "median", "estate.json")


def _manifest():
    with open(os.path.join(FIXTURES, "median", "manifest.json")) as fh:
        return json.load(fh)


def test_workbooks_shard_subdivides_and_still_completes():
    # Any workbooks page larger than 50 nodes trips a NODE_LIMIT_EXCEEDED partial.
    client = FixtureClient.from_path(MEDIAN, partial_over={"workbooks": 50})
    store = Store.open(":memory:")
    runner = ExtractRunner(client, store, "run_partial")
    runner.run()

    counts = _manifest()["counts"]

    # Extraction is COMPLETE despite the node limit: subdivision recovered it.
    assert store.count("workbooks", "run_partial") == counts["workbooks"]

    # It got there by subdividing the workbooks shard, not by accepting truncation.
    wb_subdivs = [e for e in runner.subdivision_events if e[0] == "workbooks"]
    assert wb_subdivs, "expected the workbooks shard to subdivide"

    # Page size was halved from 200 until <= 50 (200 -> 100 -> 50).
    shard = store.get_shard("run_partial", "workbooks")
    assert shard["page_size"] <= 50
    assert shard["subdivisions"] >= 1

    # Coverage reads ok, because complete data was ultimately obtained.
    cov = {r["measure"]: r["status"] for r in store.coverage("run_partial")}
    assert cov["workbooks"] == "ok"


def test_field_shards_subdivide_per_source():
    # Field shards are per-source; force a low node limit on field pages.
    client = FixtureClient.from_path(MEDIAN, partial_over={"datasource_fields": 5})
    store = Store.open(":memory:")
    runner = ExtractRunner(client, store, "run_partial_fields")
    runner.run()

    counts = _manifest()["counts"]
    assert store.count("fields", "run_partial_fields") == counts["fields_total"]
    field_subdivs = [e for e in runner.subdivision_events
                     if e[0].startswith("datasource_fields:")]
    assert field_subdivs, "expected per-source field shards to subdivide"


def test_never_accepts_truncated_data_at_minimum_page_size():
    # Threshold 0 means EVERY page (even first=1) comes back partial. The runner
    # must exhaust subdivision, fail the shard, and load nothing -- rather than
    # accept a truncated page.
    client = FixtureClient.from_path(MEDIAN, partial_over={"workbooks": 0})
    store = Store.open(":memory:")
    runner = ExtractRunner(client, store, "run_pathological")
    runner.run()

    assert store.count("workbooks", "run_pathological") == 0
    shard = store.get_shard("run_pathological", "workbooks")
    assert shard["status"] == "failed"
    assert shard["page_size"] == 1  # subdivided all the way down

    cov = {r["measure"]: r["status"] for r in store.coverage("run_pathological")}
    assert cov["workbooks"] == "failed"  # unmeasured, never silently clean
