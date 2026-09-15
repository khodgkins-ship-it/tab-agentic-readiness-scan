"""R6 calibration harness: emit the real distributions behind the provisional
thresholds so they get set from live data later (build brief section 7).

These tests exercise the emitter MECHANICS only -- that the histograms, stats,
coverage-awareness, and markdown come out right against known inputs. They
deliberately assert NOTHING about what a threshold value should be: the harness
must never tune a threshold against these synthetic fixtures (plan invariant 9),
so there is nothing here that would fail if a provisional threshold changed.

Two setups: the median fixture carried through the real pipeline (proves the
measured path over real grouped/ranked data), and hand-built in-memory stores
(proves the coverage-aware "not measured" path and the freshness/permission
arithmetic against inputs the test controls exactly).
"""

import os

from estate_scan.calibrate import (collect_calibration,
                                   render_calibration_markdown)
from estate_scan.cli import main
from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.group import assign_groups
from estate_scan.derive.rank import rank_groups
from estate_scan.derive.resolve import resolve_all
from estate_scan.extract.runner import ExtractRunner
from estate_scan.flags.engine import evaluate_flags
from estate_scan.store import Store

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _scored_store(profile="median"):
    """A store carried through the full deterministic pipeline -- the state the
    calibration harness reads: groups, ranked variants, and coverage rows."""
    estate = os.path.join(FIXTURES, profile, "estate.json")
    client = FixtureClient.from_path(estate)
    config = client.run_config()
    store = Store.open(":memory:")
    ExtractRunner(client, store, "r").run()
    resolve_all(store, "r")
    assign_groups(store, "r", core_metrics=config.get("core_metrics") or None)
    rank_groups(store, "r")
    evaluate_flags(store, "r")
    return store


def _section(summary, key):
    for s in summary["sections"]:
        if s["key"] == key:
            return s
    raise AssertionError("no section %r in calibration summary" % key)


def _covered(run_id, measures):
    """An in-memory store with a runs row and the given coverage measures, so
    the coverage-aware gating can be exercised without a full scan."""
    store = Store.open(":memory:")
    store.start_run(run_id, {"site_name": "unit", "deployment_type": "cloud"})
    for measure, (status, reason) in measures.items():
        store.record_coverage(run_id, measure, status, reason)
    return store


# -- measured path over the real pipeline ------------------------------------

def test_variant_count_distribution_matches_the_store():
    store = _scored_store("median")
    summary = collect_calibration(store, "r")
    s = _section(summary, "metric_variant_count")

    assert s["measured"] is True
    # The histogram is the real per-group variant counts, recomputed read-only.
    groups = store.metric_groups("r")
    expected = {}
    for g in groups:
        c = len(store.metric_variants("r", g["group_id"]))
        expected[c] = expected.get(c, 0) + 1
    assert s["histogram"] == expected
    assert s["n"] == len(groups)
    assert sum(s["histogram"].values()) == len(groups)
    assert s["stats"]["n"] == len(groups)
    # It reports the CURRENT provisional threshold, marked provisional -- but
    # the section is a distribution, not a proposed value.
    assert s["threshold"]["flag"] == "SEM-01"
    assert s["threshold"]["provisional"] is True


def test_dominance_distribution_is_measured_and_consistent():
    store = _scored_store("median")
    summary = collect_calibration(store, "r")
    s = _section(summary, "usage_dominance")

    assert s["measured"] is True
    # Every group with measured usage contributes exactly one share observation.
    groups = store.metric_groups("r")
    measured = 0
    for g in groups:
        views = [m["view_count"] for m in store.metric_variants("r", g["group_id"])]
        if sum(views) > 0:
            measured += 1
    assert s["n"] == measured
    assert sum(b["count"] for b in s["share"]["buckets"]) == measured
    assert sum(s["cover80"]["histogram"].values()) == measured
    # A ratio needs a runner-up, so it can only be a subset of measured groups.
    assert s["ratio"]["n_with_runner_up"] <= measured
    # Shares are real fractions of group views.
    assert s["share"]["stats"]["min"] >= 0.0
    assert s["share"]["stats"]["max"] <= 1.0


# -- coverage-aware "not measured" path --------------------------------------

def test_unmeasured_sections_report_not_measured_not_clean():
    # A metadata-only-shaped run: fields/usage measured, but refresh and
    # permissions were never collected.
    store = _covered("r", {
        "fields": ("ok", ""),
        "usage_events": ("ok", ""),
        "refresh_jobs": ("skipped", "rest_jobs capability absent"),
        "permissions": ("skipped", "permissions not sampled"),
    })
    summary = collect_calibration(store, "r")

    fresh = _section(summary, "refresh_freshness")
    perms = _section(summary, "permission_exposure")
    assert fresh["measured"] is False
    assert fresh["coverage_status"] == "skipped"
    assert fresh["coverage_reason"] == "rest_jobs capability absent"
    assert "jobs_total" not in fresh          # nothing computed from absent data
    assert perms["measured"] is False
    assert perms["coverage_status"] == "skipped"

    text = render_calibration_markdown(summary)
    assert "Not measured" in text
    # The unmeasured section must not read as a clean estate.
    assert "not because the estate is clean" in text


def test_absent_coverage_measure_is_not_measured():
    # No coverage rows recorded at all -> every section reports absent, never
    # silently clean.
    store = _covered("r", {})
    summary = collect_calibration(store, "r")
    for s in summary["sections"]:
        assert s["measured"] is False
        assert s["coverage_status"] == "absent"


# -- freshness / permission arithmetic against controlled inputs -------------

def test_freshness_failure_rate_arithmetic():
    store = _covered("r", {"refresh_jobs": ("ok", "")})
    store.load_refresh_jobs("r", [
        {"task_id": "t1", "datasource_id": "d1", "status": "Success"},
        {"task_id": "t2", "datasource_id": "d2", "status": "Success"},
        {"task_id": "t3", "datasource_id": "d3", "status": "Success"},
        {"task_id": "t4", "datasource_id": "d4", "status": "Success"},
        {"task_id": "t5", "datasource_id": "d5", "status": "Failed"},
    ])
    store.commit()
    s = _section(collect_calibration(store, "r"), "refresh_freshness")

    assert s["measured"] is True
    assert s["jobs_total"] == 5
    assert s["jobs_failed"] == 1
    assert s["failure_rate"] == 0.2


def test_permission_exposure_classification():
    store = _covered("r", {"permissions": ("ok", "")})
    store.load_permissions("r", [
        # sensitive capability to everyone -> counts, two distinct objects
        {"object_type": "project", "object_id": "p1", "grantee_type": "group",
         "grantee_id": "AllUsers", "capability": "Write", "mode": "Allow"},
        {"object_type": "project", "object_id": "p2", "grantee_type": "group",
         "grantee_id": "AllUsers", "capability": "Delete", "mode": "Allow"},
        # everyone but not a sensitive capability
        {"object_type": "project", "object_id": "p1", "grantee_type": "group",
         "grantee_id": "AllUsers", "capability": "Read", "mode": "Allow"},
        # sensitive but not everyone
        {"object_type": "project", "object_id": "p1", "grantee_type": "group",
         "grantee_id": "analytics", "capability": "Write", "mode": "Allow"},
        # everyone + sensitive but denied, not granted (distinct object +
        # capability so it does not collide with the Write/Allow grant above)
        {"object_type": "project", "object_id": "p3", "grantee_type": "group",
         "grantee_id": "AllUsers", "capability": "ChangePermissions",
         "mode": "Deny"},
    ])
    store.commit()
    s = _section(collect_calibration(store, "r"), "permission_exposure")

    assert s["measured"] is True
    assert s["grants_total"] == 5
    assert s["permissive_grants"] == 2
    assert s["exposed_objects"] == 2
    assert s["by_capability"] == {"Write": 1, "Delete": 1}


# -- rendering states provisional, tunes nothing -----------------------------

def test_render_states_provisional_and_tunes_nothing():
    store = _scored_store("median")
    text = render_calibration_markdown(collect_calibration(store, "r"))

    assert "# Tableau Estate Scan — threshold calibration" in text
    assert "provisional" in text
    assert "Nothing here changes a threshold" in text
    assert "not applied here" in text
    # It emits distributions, not a proposal: no recommended/suggested value.
    lower = text.lower()
    assert "recommend" not in lower
    assert "suggested threshold" not in lower


# -- CLI ---------------------------------------------------------------------

def test_cli_calibrate_writes_report(tmp_path, capsys):
    out = str(tmp_path / "run")
    assert main(["scan", "--fixture", os.path.join(FIXTURES, "median"),
                 "--out", out]) == 0
    capsys.readouterr()

    assert main(["calibrate", "--out", out]) == 0
    report = os.path.join(out, "calibration.md")
    assert os.path.exists(report)
    with open(report, encoding="utf-8") as fh:
        body = fh.read()
    assert "threshold calibration" in body
    console = capsys.readouterr().out
    assert "calibrate" in console


def test_cli_calibrate_stdout(tmp_path, capsys):
    out = str(tmp_path / "run")
    assert main(["scan", "--fixture", os.path.join(FIXTURES, "median"),
                 "--out", out]) == 0
    capsys.readouterr()

    assert main(["calibrate", "--out", out, "--stdout"]) == 0
    printed = capsys.readouterr().out
    assert "# Tableau Estate Scan — threshold calibration" in printed
    # --stdout does not also write the file.
    assert not os.path.exists(os.path.join(out, "calibration.md"))
