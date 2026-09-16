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
    # Attempted measures succeeded -- including the R2 dimensions (permissions,
    # refresh_jobs, custom_sql), the global Metadata shards database_tables /
    # data_quality_warnings, and adoption_depth (usage events carry a user).
    for m in ("projects", "datasources", "workbooks", "fields", "usage_events",
              "permissions", "refresh_jobs", "custom_sql", "adoption_depth",
              "database_tables", "data_quality_warnings", "column_lineage"):
        assert cov.get(m) == "ok", "measure %s not ok: %r" % (m, cov.get(m))
    # Still-deferred measures are recorded as skipped -- never absent, never clean.
    for m in ("query_execution", "adoption_trajectory"):
        assert cov.get(m) == "skipped", "measure %s should be skipped" % m


@pytest.mark.parametrize("profile", ["median", "small", "hostile"])
def test_r2_tables_match_manifest(profile):
    """The four R2 dimensions (custom SQL grain, refresh freshness, permissions,
    adoption depth) populate their tables to exactly the ground truth the fixture
    generator recorded -- counts and derived grain signals both."""
    estate_path, _ = _paths(profile)
    store = Store.open(":memory:")
    ExtractRunner(FixtureClient.from_path(estate_path), store, "r").run()
    man = _manifest(profile)
    c = store.conn

    def scalar(sql):
        return c.execute(sql).fetchone()[0]

    # Custom SQL -> grain (DF-07): count plus the two grain signals, which are
    # derived from the SQL text by the loader, not carried in the fixture.
    cs = man["custom_sql"]
    assert store.count("custom_sql", "r") == cs["count"]
    assert scalar("SELECT COALESCE(SUM(has_group_by),0) FROM custom_sql "
                  "WHERE run_id='r'") == cs["with_group_by"]
    assert scalar("SELECT COALESCE(SUM(has_user_function),0) FROM custom_sql "
                  "WHERE run_id='r'") == cs["with_user_function"]

    # Refresh/job history -> freshness (DF-05/06).
    rj = man["refresh_jobs"]
    assert store.count("refresh_jobs", "r") == rj["count"]
    assert scalar("SELECT COUNT(*) FROM refresh_jobs "
                  "WHERE run_id='r' AND status='Failed'") == rj["failed"]

    # Permissions (SEC-02, governance): project-level in full, content-level
    # sampled -- the sampling basis is a first-class recorded fact.
    pm = man["permissions"]
    assert store.count("permissions", "r") == pm["count"]
    assert scalar("SELECT COUNT(*) FROM permissions "
                  "WHERE run_id='r' AND object_type='project'") == pm["project_level"]
    assert scalar("SELECT COUNT(*) FROM permissions "
                  "WHERE run_id='r' AND sampled=1") == pm["sampled"]

    # Adoption depth (ADO-01): usage events now carry a user, the ceiling on
    # per-user penetration that was always NULL in the prototype.
    ad = man["adoption_depth"]
    assert scalar("SELECT COUNT(*) FROM usage_events "
                  "WHERE run_id='r' AND user_id IS NOT NULL") == ad["events_with_user"]
    assert scalar("SELECT COUNT(DISTINCT user_id) FROM usage_events "
                  "WHERE run_id='r' AND user_id IS NOT NULL") == ad["distinct_users"]

    # Root-table column projection (DF-08): one row per (source, physical table,
    # column) a ColumnField maps onto, from ColumnField.upstreamColumns. The
    # loader records it; the fixture ground truth counts the same rows.
    tcp = man["table_column_projection"]
    assert store.count("table_column_projection", "r") == tcp["rows"]

    # Database tables -> grain (DF-07 companion): count plus the derived signals
    # (embedded / certified / the largest physical-table fan-out).
    dt = man["database_tables"]
    assert store.count("database_tables", "r") == dt["count"]
    assert scalar("SELECT COALESCE(SUM(is_embedded),0) FROM database_tables "
                  "WHERE run_id='r'") == dt["embedded"]
    assert scalar("SELECT COALESCE(SUM(is_certified),0) FROM database_tables "
                  "WHERE run_id='r'") == dt["certified"]
    assert scalar("SELECT COALESCE(MAX(downstream_datasource_count),0) FROM "
                  "database_tables WHERE run_id='r'") == dt["max_downstream"]

    # Data-quality warnings (GOV-03, freshness context): count plus the active
    # and severe splits that governance divergence keys off.
    dq = man["data_quality_warnings"]
    assert store.count("data_quality_warnings", "r") == dq["count"]
    assert scalar("SELECT COALESCE(SUM(is_active),0) FROM data_quality_warnings "
                  "WHERE run_id='r'") == dq["active"]
    assert scalar("SELECT COALESCE(SUM(is_severe),0) FROM data_quality_warnings "
                  "WHERE run_id='r'") == dq["severe"]


def test_custom_sql_grain_signals_are_derived_not_leaked():
    """Every grain signal the loader sets must be justified by the SQL text it
    stored -- proving the flag is derived from `query`, not lifted from a hidden
    ground-truth key the fixture could have leaked."""
    estate_path, _ = _paths("median")
    store = Store.open(":memory:")
    ExtractRunner(FixtureClient.from_path(estate_path), store, "r").run()
    rows = store.conn.execute(
        "SELECT query, char_length, has_group_by, has_user_function "
        "FROM custom_sql WHERE run_id='r'").fetchall()
    assert rows, "custom_sql must be populated"
    for r in rows:
        q = r["query"] or ""
        assert q and r["char_length"] == len(q)
        if r["has_group_by"]:
            assert "group by" in q.lower()
        if r["has_user_function"]:
            low = q.lower()
            assert any(t in low for t in
                       ("current_user", "session_user", "system_user",
                        "user(", "username(")), q


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
    man = _manifest("median")
    counts = man["counts"]

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
    # The R2 dimensions -- extracted after the crash point (custom_sql closes the
    # global GraphQL order; refresh_jobs/permissions are REST steps after usage) --
    # also land exactly once on resume.
    assert store2.count("custom_sql", "r") == man["custom_sql"]["count"]
    assert store2.count("refresh_jobs", "r") == man["refresh_jobs"]["count"]
    assert store2.count("permissions", "r") == man["permissions"]["count"]
    cov = {r["measure"]: r["status"] for r in store2.coverage("r")}
    assert cov["workbooks"] == "ok" and cov["fields"] == "ok"
    for m in ("custom_sql", "refresh_jobs", "permissions", "adoption_depth"):
        assert cov[m] == "ok", "R2 measure %s not ok after resume: %r" % (m, cov.get(m))


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


# -- coverage honesty on failure ------------------------------------------------
# A query the live site's Metadata API schema does not support must degrade to
# an honest "unavailable" (with the reason), NOT "failed" and NOT silently
# clean. A failure for any other reason stays "failed". This is coverage-first-
# class (plan invariant 7): an unmeasured dimension never reads as clean, and
# the register distinguishes "your site can't provide this" from "it broke".
# Regression guard for the real live scan finding (projectsConnection / a
# CalculatedField field absent from the site schema).

def _coverage_runner():
    store = Store.open(":memory:")
    return ExtractRunner(client=None, store=store, run_id="r"), store


def test_schema_incompatible_query_is_unavailable_not_failed():
    from estate_scan.extract.shards import global_shard
    runner, store = _coverage_runner()
    shard = global_shard("projects", {"page_size": 100})
    shard.status = "failed"
    runner._shard_errors[shard.shard_key] = (
        "Validation error (FieldUndefined@[projectsConnection]) : Field "
        "'projectsConnection' in type 'Query' is undefined")
    runner._record_measure("projects", shard, ok=False)

    row = {r["measure"]: (r["status"], r["reason"])
           for r in store.coverage("r")}["projects"]
    status, reason = row
    assert status == "unavailable"          # honest: not clean, not "failed"
    assert "Metadata API schema" in reason
    assert "projectsConnection" in reason   # the real cause is surfaced


def test_non_schema_failure_stays_failed():
    from estate_scan.extract.shards import global_shard
    runner, store = _coverage_runner()
    shard = global_shard("workbooks", {"page_size": 100})
    shard.status = "failed"
    runner._shard_errors[shard.shard_key] = "SESSION_EXPIRED"
    runner._record_measure("workbooks", shard, ok=False)

    row = {r["measure"]: (r["status"], r["reason"])
           for r in store.coverage("r")}["workbooks"]
    status, reason = row
    assert status == "failed"               # a transient/other failure, not schema
    assert "SESSION_EXPIRED" in reason
