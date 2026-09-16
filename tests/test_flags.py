"""M5 acceptance (build brief section 5):

  - thresholds change in rules.yaml and flag output changes with no code edit
  - suppressions appear in the run log

Plus correctness against the median manifest's `flags_expected`. The engine
holds no thresholds and no firing decisions a threshold could express -- those
live in the rules file -- so both acceptance criteria are demonstrated by
handing the engine a modified rules mapping and observing the output move,
without touching engine.py.
"""

import copy
import json
import os

import pytest
import yaml

from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.group import assign_groups
from estate_scan.derive.rank import rank_groups
from estate_scan.derive.resolve import resolve_all
from estate_scan.extract.runner import ExtractRunner
from estate_scan.flags.engine import evaluate_flags, load_rules, log_lines
from estate_scan.store import Store

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _store(profile="median"):
    """A store carried through extract -> resolve -> group -> rank, the state
    the flag engine reads."""
    estate = os.path.join(FIXTURES, profile, "estate.json")
    client = FixtureClient.from_path(estate)
    core = client.run_config()["core_metrics"]
    store = Store.open(":memory:")
    ExtractRunner(client, store, "r").run()
    resolve_all(store, "r")
    assign_groups(store, "r", core_metrics=core)
    rank_groups(store, "r")
    return store


def _manifest(profile="median"):
    with open(os.path.join(FIXTURES, profile, "manifest.json")) as fh:
        return json.load(fh)


def _by_flag(store):
    """flag_id -> (row, parsed evidence). Estate-scoped run: one row per flag."""
    out = {}
    for row in store.flags("r"):
        out[row["flag_id"]] = (row, json.loads(row["evidence_json"]))
    return out


# -- correctness against the manifest ----------------------------------------

def test_prototype_flags_match_manifest():
    store = _store("median")
    summary = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    expected = _manifest("median")["flags_expected"]
    fired = {f["flag"] for f in summary["fired"]}
    rows = _by_flag(store)

    # every implemented flag the manifest says fires, fired -- and is written
    for flag_id, exp in expected.items():
        if exp["fires"]:
            assert flag_id in fired, "%s should fire" % flag_id
            assert flag_id in rows, "%s should be written" % flag_id
        else:
            assert flag_id not in fired, "%s should not fire" % flag_id
            assert flag_id not in rows, "%s should not be written" % flag_id

    # SEC-01: 22 calculated fields carry a user-context function
    assert rows["SEC-01"][0]["count"] == expected["SEC-01"]["count"] == 22

    # SEM-01: every core metric has more than five variants
    assert rows["SEM-01"][1]["groups"] == expected["SEM-01"]["groups"]

    # SEM-02: the non-dominant groups with real usage disagreement
    assert rows["SEM-02"][1]["groups"] == expected["SEM-02"]["groups"]

    # SEM-03 describability sits above threshold, so it must be silent -- an
    # unmeasured facet is never a clean one, but a measured pass is.
    assert "SEM-03" not in rows

    # DF-01 embedded exposure share
    assert rows["DF-01"][1]["embedded_share"] == expected["DF-01"]["embedded_share"]

    # DF-02 upstream table fan-out (max sources on one physical table)
    assert rows["DF-02"][1]["max_sources_per_table"] == expected["DF-02"]["count"] == 12

    # DF-03 longest published-on-published chain
    assert rows["DF-03"][1]["depth"] == expected["DF-03"]["depth"] == 2

    # EST-01 zero-view workbooks
    assert rows["EST-01"][0]["count"] == expected["EST-01"]["count"] == 150

    # ADO-02 view concentration
    assert (rows["ADO-02"][1]["workbooks_covering_80pct_views"]
            == expected["ADO-02"]["workbooks_covering_80pct_views"] == 106)

    # R4 data-foundation flags fire on the median estate; their counts match the
    # fixture ground truth (computed in generate.py, not tuned to a threshold).
    assert rows["DF-04"][0]["count"] == expected["DF-04"]["count"]
    assert rows["DF-05"][0]["count"] == expected["DF-05"]["count"]
    assert rows["DF-06"][0]["count"] == expected["DF-06"]["count"]

    # GOV-03: certified sources carrying an active data-quality warning -- the
    # divergence case injected in the fixture. Count matches ground truth and the
    # evidence lists the divergent sources.
    assert rows["GOV-03"][0]["count"] == expected["GOV-03"]["count"]
    assert rows["GOV-03"][1]["count"] == expected["GOV-03"]["count"]
    assert len(rows["GOV-03"][1]["sources"]) == expected["GOV-03"]["count"]

    # GOV-02: the estate has warnings, so "the feature is unused" is silent -- a
    # measured feed with signal is not a clean one it invents.
    assert "GOV-02" not in rows


def test_catalog_is_complete_and_unimplemented_flags_are_defined_not_evaluated():
    # The file is the complete catalog from day one: flags marked
    # implemented:false are recorded as defined-but-not-evaluated, never as
    # clean. That keeps coverage honest.
    store = _store("median")
    summary = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    rules = load_rules()
    defined = set(rules["flags"].keys())
    implemented = {fid for fid, s in rules["flags"].items()
                   if s.get("implemented")}
    unimplemented = defined - implemented

    assert unimplemented, "prototype leaves later flags defined-but-unimplemented"
    assert set(summary["unimplemented"]) == unimplemented
    # nothing implemented was silently dropped
    assert summary["skipped"] == []


# -- acceptance: thresholds drive firing, with no code edit -------------------

def test_threshold_change_in_rules_changes_output_without_code_edit(tmp_path):
    store = _store("median")

    # Baseline from the shipped rules: SEM-01 fires (variants > 5).
    base = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    assert "SEM-01" in {f["flag"] for f in base["fired"]}

    # Raise ONLY the threshold in a copy of the rules file. No metric group has
    # more than 47 variants, so SEM-01 must go silent -- purely from the file.
    rules = load_rules()
    rules["flags"]["SEM-01"]["threshold"]["variant_count_gt"] = 100
    alt = tmp_path / "rules_high.yaml"
    alt.write_text(yaml.safe_dump(rules))

    after = evaluate_flags(store, "r", rules_path=str(alt),
                           now="2026-01-01T00:00:00Z")
    assert "SEM-01" not in {f["flag"] for f in after["fired"]}
    assert "SEM-01" not in _by_flag(store)

    # And it comes back when the threshold drops again -- still no code change.
    rules["flags"]["SEM-01"]["threshold"]["variant_count_gt"] = 5
    alt2 = tmp_path / "rules_low.yaml"
    alt2.write_text(yaml.safe_dump(rules))
    again = evaluate_flags(store, "r", rules_path=str(alt2),
                           now="2026-01-01T00:00:00Z")
    assert "SEM-01" in {f["flag"] for f in again["fired"]}


def test_lowering_a_threshold_can_make_a_silent_flag_fire(tmp_path):
    store = _store("median")

    # SEM-03 describability is ~0.547, above the shipped 0.40 floor, so silent.
    base = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    assert "SEM-03" not in {f["flag"] for f in base["fired"]}

    # Raise the required coverage above the observed value: now it fires.
    rules = load_rules()
    rules["flags"]["SEM-03"]["threshold"]["min_coverage"] = 0.90
    alt = tmp_path / "rules.yaml"
    alt.write_text(yaml.safe_dump(rules))
    after = evaluate_flags(store, "r", rules_path=str(alt),
                           now="2026-01-01T00:00:00Z")
    assert "SEM-03" in {f["flag"] for f in after["fired"]}


# -- R4: firing proven by the rules file, not by shaping the fixture ----------

def test_sec02_fires_when_everyone_grantee_list_widens(tmp_path):
    store = _store("median")

    # Shipped rules: AllUsers holds only [Read], so SEC-02 is silent -- and the
    # fixture is NOT shaped to make it fire (build brief 7).
    base = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    assert "SEC-02" not in {f["flag"] for f in base["fired"]}

    # Treat Analysts as an "everyone" group too. Analysts holds [Read, Write]
    # Allow at every project, so the Write grant now reads as permissive -- the
    # firing path is proven purely from the rules file, no code or fixture edit.
    rules = load_rules()
    rules["flags"]["SEC-02"]["threshold"]["everyone_grantees"] = \
        ["AllUsers", "Analysts"]
    alt = tmp_path / "rules.yaml"
    alt.write_text(yaml.safe_dump(rules))
    after = evaluate_flags(store, "r", rules_path=str(alt),
                           now="2026-01-01T00:00:00Z")
    fired = {f["flag"] for f in after["fired"]}
    assert "SEC-02" in fired
    assert "SEC-02" in _by_flag(store)


def test_gov02_fires_only_on_a_measured_feed_with_zero_warnings():
    """GOV-02 is the coverage-honesty flag: "no data-quality warnings" is a real
    signal only when the DQW feed was actually measured. No shipped fixture is
    shaped to fire it (every estate carries warnings), so the firing path and its
    coverage gate are proven here by driving the store directly -- not by editing
    a fixture (build brief 7)."""
    store = _store("median")

    # As shipped: the median estate carries warnings, so GOV-02 is silent.
    base = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    assert "GOV-02" not in {f["flag"] for f in base["fired"]}

    # Remove every warning while the feed stays measured (coverage `ok`): now the
    # estate genuinely uses no data-quality warnings, so GOV-02 fires.
    store.conn.execute("DELETE FROM data_quality_warnings WHERE run_id='r'")
    store.conn.commit()
    assert store.coverage_status("r", "data_quality_warnings") == "ok"
    fired = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    assert "GOV-02" in {f["flag"] for f in fired["fired"]}
    _, ev = _by_flag(store)["GOV-02"]
    assert ev["warning_count"] == 0 and ev["measured"] is True
    # GOV-03 has no divergence to find once the warnings are gone.
    assert "GOV-03" not in _by_flag(store)

    # Now mark the feed unmeasured (the live case where the DQW API is off): zero
    # warnings must NOT read as health -- GOV-02 goes silent again.
    store.record_coverage("r", "data_quality_warnings", "unavailable",
                          "data quality API not enabled on this site")
    after = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    assert "GOV-02" not in {f["flag"] for f in after["fired"]}
    assert "GOV-02" not in _by_flag(store)


def test_df07_grain_flag_is_suppressed_but_evaluated():
    store = _store("median")
    summary = evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")

    # DF-07 is implemented but suppressed: never written and never in
    # flags_expected, but still evaluated so the log can say it WOULD fire and
    # how many custom-SQL grain risks it hid.
    assert "DF-07" not in _by_flag(store)
    assert "DF-07" not in {f["flag"] for f in summary["fired"]}
    suppressed = {s["flag"]: s for s in summary["suppressed"]}
    assert "DF-07" in suppressed
    assert suppressed["DF-07"]["would_fire"] is True
    manifest = _manifest("median")
    assert suppressed["DF-07"]["count"] == manifest["custom_sql"]["with_group_by"]


# -- acceptance: suppressions appear in the run log ---------------------------

def test_suppressed_flag_is_evaluated_logged_and_not_written(tmp_path):
    store = _store("median")

    # Flip an implemented, firing flag (SEC-01) to suppressed in the rules file.
    rules = load_rules()
    rules["flags"]["SEC-01"]["suppress"] = True
    alt = tmp_path / "rules.yaml"
    alt.write_text(yaml.safe_dump(rules))

    summary = evaluate_flags(store, "r", rules_path=str(alt),
                             now="2026-01-01T00:00:00Z")

    # Not written to the flags table...
    assert "SEC-01" not in _by_flag(store)
    assert "SEC-01" not in {f["flag"] for f in summary["fired"]}

    # ...but still evaluated, so the log can say it WOULD have fired and hid 22.
    suppressed = {s["flag"]: s for s in summary["suppressed"]}
    assert "SEC-01" in suppressed
    assert suppressed["SEC-01"]["would_fire"] is True
    assert suppressed["SEC-01"]["count"] == 22

    log = "\n".join(log_lines(summary))
    assert "SUPPRESSED SEC-01" in log
    assert "would_fire=True" in log


# -- the flags table is rebuilt each run, never appended ----------------------

def test_reevaluation_clears_prior_flags(tmp_path):
    store = _store("median")
    evaluate_flags(store, "r", now="2026-01-01T00:00:00Z")
    first = len(store.flags("r"))
    assert first > 0

    # Suppress everything implemented; a re-run must clear the prior rows, not
    # accumulate them.
    rules = load_rules()
    for spec in rules["flags"].values():
        if spec.get("implemented"):
            spec["suppress"] = True
    alt = tmp_path / "rules.yaml"
    alt.write_text(yaml.safe_dump(rules))
    evaluate_flags(store, "r", rules_path=str(alt), now="2026-01-01T00:00:00Z")
    assert len(store.flags("r")) == 0
