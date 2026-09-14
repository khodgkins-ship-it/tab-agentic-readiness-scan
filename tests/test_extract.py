"""M2 acceptance: the median fixture extracts fully, resumes after a mid-run
kill, and coverage records every attempted measure."""

import json
import os

import pytest

from estate_scan.clients.fixture import FixtureClient
from estate_scan.extract.runner import ExtractRunner
from estate_scan.store import Store

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _paths(profile):
    base = os.path.join(FIXTURES, profile)
    return os.path.join(base, "estate.json"), os.path.join(base, "manifest.json")


def _manifest(profile):
    with open(_paths(profile)[1]) as fh:
        return json.load(fh)


@pytest.mark.parametrize("profile", ["median", "small", "hostile"])
def test_full_extract_matches_manifest(profile):
    estate_path, _ = _paths(profile)
    client = FixtureClient.from_path(estate_path)
    store = Store.open(":memory:")
    ExtractRunner(client, store, "r").run()

    counts = _manifest(profile)["counts"]
    assert store.count("projects", "r") == counts["projects"]
    assert store.count("datasources", "r") == counts["datasources"]
    assert store.count("workbooks", "r") == counts["workbooks"]
    assert store.count("fields", "r") == counts["fields_total"]
    calc = store.conn.execute(
        "SELECT COUNT(*) c FROM fields WHERE run_id='r' AND is_calculated=1"
    ).fetchone()["c"]
    assert calc == counts["calculated_fields"]


def test_coverage_records_every_attempted_measure():
    estate_path, _ = _paths("median")
    client = FixtureClient.from_path(estate_path)
    store = Store.open(":memory:")
    ExtractRunner(client, store, "r").run()

    cov = {r["measure"]: r["status"] for r in store.coverage("r")}
    # Attempted measures succeeded.
    for m in ("projects", "datasources", "workbooks", "fields", "usage_events"):
        assert cov.get(m) == "ok", "measure %s not ok: %r" % (m, cov.get(m))
    # Deferred measures are recorded as skipped -- never absent, never clean.
    for m in ("permissions", "refresh_jobs", "custom_sql", "database_tables",
              "data_quality_warnings", "query_execution", "adoption_trajectory"):
        assert cov.get(m) == "skipped", "measure %s should be skipped" % m


def test_run_metadata_records_query_set_version():
    estate_path, _ = _paths("median")
    client = FixtureClient.from_path(estate_path)
    store = Store.open(":memory:")
    ExtractRunner(client, store, "r").run()
    run = store.get_run("r")
    assert run["query_set_version"] == "v1"
    assert run["mode"] == "scan"
    assert run["completed_at"] is not None
    assert run["model_pass"] == 0  # local-first: no model pass by default


def test_resume_after_mid_run_kill(tmp_path):
    estate_path, _ = _paths("median")
    db = str(tmp_path / "resume.db")
    counts = _manifest("median")["counts"]

    # First run: crash after the 4th committed page (well into workbooks).
    calls = {"n": 0}

    def kill_hook(shard, page_index):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("simulated kill")

    store = Store.open(db)
    runner = ExtractRunner(FixtureClient.from_path(estate_path), store, "r",
                           page_hook=kill_hook)
    with pytest.raises(RuntimeError):
        runner.run()

    # Progress persisted but run not complete; workbooks partially loaded.
    assert store.get_run("r") is None or store.get_run("r")["completed_at"] is None
    partial_wb = store.count("workbooks", "r")
    assert 0 < partial_wb < counts["workbooks"]
    store.close()

    # Second run: fresh client + runner, same db + run_id, no kill hook.
    store2 = Store.open(db)
    ExtractRunner(FixtureClient.from_path(estate_path), store2, "r").run()

    # Everything landed exactly once (INSERT OR REPLACE => no duplicates).
    assert store2.count("projects", "r") == counts["projects"]
    assert store2.count("datasources", "r") == counts["datasources"]
    assert store2.count("workbooks", "r") == counts["workbooks"]
    assert store2.count("fields", "r") == counts["fields_total"]
    assert store2.get_run("r")["completed_at"] is not None
    cov = {r["measure"]: r["status"] for r in store2.coverage("r")}
    assert cov["workbooks"] == "ok" and cov["fields"] == "ok"


def test_rerun_is_idempotent():
    # Running the whole extraction twice into the same store must not duplicate.
    estate_path, _ = _paths("small")
    counts = _manifest("small")["counts"]
    store = Store.open(":memory:")
    ExtractRunner(FixtureClient.from_path(estate_path), store, "r").run()
    # A second full run re-processes every shard (they are already complete, so
    # they are skipped) -- counts stay put.
    ExtractRunner(FixtureClient.from_path(estate_path), store, "r").run()
    assert store.count("workbooks", "r") == counts["workbooks"]
    assert store.count("datasources", "r") == counts["datasources"]
