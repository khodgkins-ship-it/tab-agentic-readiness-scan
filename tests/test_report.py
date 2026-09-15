"""M7 acceptance (build brief section 5):

  - the presentation build contains no formula text (a correctness test, not a
    style test) and no individual owner names
  - the app opens from file:// with networking disabled -- encoded here as the
    embedded payload being valid JSON and the file carrying no external
    references, the two failures that break an offline open. The live file://
    render was also verified by hand against the median fixture.
  - print output is exercised on the median and small fixtures
  - findings.json never gains a top-level score field
  - two builds from one run, both emitted, and which builds were produced is
    recorded in the run log
  - the pre-emit secret scan aborts the whole emit on a hit rather than warning
"""

import copy
import json
import os
import re

import pytest
from openpyxl import load_workbook

from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.group import assign_groups
from estate_scan.derive.rank import rank_groups
from estate_scan.derive.resolve import resolve_all
from estate_scan.extract.runner import ExtractRunner
from estate_scan.flags.engine import evaluate_flags
from estate_scan.report import emit
from estate_scan.report.compare import compare_runs, render_comparison_markdown
from estate_scan.report.emit import emit_all
from estate_scan.report.findings import build_findings
from estate_scan.report.markdown import render_markdown
from estate_scan.report.redact import (SecretLeak, assert_no_secrets, mark_working,
                                        redact)
from estate_scan.report.webapp import render_html, webapp_payload
from estate_scan.score import score
from estate_scan.store import Store

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# The scorer's contract keys plus the report superset -- and never `score`.
_FINDINGS_KEYS = {"meta", "facets", "domains", "flags", "coverage", "findings"}


def _scored_store(profile="median"):
    estate = os.path.join(FIXTURES, profile, "estate.json")
    client = FixtureClient.from_path(estate)
    config = client.run_config()
    store = Store.open(":memory:")
    ExtractRunner(client, store, "r").run()
    resolve_all(store, "r")
    assign_groups(store, "r", core_metrics=config.get("core_metrics") or None)
    rank_groups(store, "r")
    evaluate_flags(store, "r")
    score(store, "r", config=config)     # persists score_output
    return store, config


def _emit(profile, out_dir, build="presentation", framing="full"):
    store, _config = _scored_store(profile)
    paths = emit_all(store, "r", str(out_dir), build=build, framing=framing)
    return paths


def _embedded_payload(html):
    m = re.search(
        r'<script id="findings-data" type="application/json">(.*?)</script>',
        html, re.DOTALL)
    assert m, "no embedded findings payload"
    return json.loads(m.group(1))


def _working_formulas(findings):
    """Real calculated expressions in the working findings -- the needles the
    presentation build must not contain. Restricted to expressions carrying a
    function call so we never match on a bare field name that legitimately
    appears in the presentation build."""
    out = set()
    for g in findings["findings"]["definition_multiplicity"]["groups"]:
        for v in g["variants"]:
            rf = v.get("resolved_formula")
            if rf and rf != "[redacted]" and "(" in rf:
                out.add(rf)
    for fld in findings["findings"]["security_exposure"].get("fields", []):
        fo = fld.get("formula")
        if fo and "(" in fo:
            out.add(fo)
    return out


# -- the flagship correctness test -------------------------------------------

def test_presentation_build_contains_no_formula_text(tmp_path):
    _emit("median", tmp_path)
    working = json.loads((tmp_path / "findings.json").read_text())
    needles = _working_formulas(working)
    assert needles, "fixture should carry resolved formulas to make this meaningful"

    pres = (tmp_path / "report.presentation.html").read_text(encoding="utf-8")
    for formula in needles:
        assert formula not in pres, "formula text leaked into presentation build"

    # And the working build DOES carry them -- otherwise the test proves nothing.
    work = (tmp_path / "report.working.html").read_text(encoding="utf-8")
    assert any(f in work for f in needles)


def test_presentation_payload_redacts_formula_and_owner(tmp_path):
    _emit("median", tmp_path)
    pres = (tmp_path / "report.presentation.html").read_text(encoding="utf-8")
    payload = _embedded_payload(pres)
    for g in payload["findings"]["definition_multiplicity"]["groups"]:
        for v in g["variants"]:
            assert v["resolved_formula"] in (None, "[redacted]")
            assert v["owner"] in (None, "[redacted]")


def test_presentation_build_has_no_owner_names(tmp_path):
    _emit("median", tmp_path)
    working = json.loads((tmp_path / "findings.json").read_text())
    owners = set()
    for g in working["findings"]["definition_multiplicity"]["groups"]:
        for v in g["variants"]:
            if v.get("owner") and v["owner"] != "[redacted]":
                owners.add(v["owner"])
    for w in working["findings"]["security_exposure"].get("affected_workbooks", []):
        if w.get("owner"):
            owners.add(w["owner"])
    assert owners, "fixture should carry owner names"
    pres = (tmp_path / "report.presentation.html").read_text(encoding="utf-8")
    for owner in owners:
        assert not re.search(r"\b" + re.escape(owner) + r"\b", pres), \
            "owner name leaked into presentation build"


# -- offline / self-contained ------------------------------------------------

@pytest.mark.parametrize("profile", ["median", "small"])
def test_app_is_self_contained_and_offline(tmp_path, profile):
    _emit(profile, tmp_path)
    for name in ("report.presentation.html", "report.working.html"):
        html = (tmp_path / name).read_text(encoding="utf-8")
        # No network of any kind: no absolute URLs, no protocol-relative refs,
        # no external stylesheet/script/font.
        assert "http://" not in html
        assert "https://" not in html
        assert "<link" not in html
        assert "<script src" not in html
        assert "@import" not in html
        assert re.search(r'src\s*=\s*["\']//', html) is None
        # Styles and script were inlined -- no unreplaced template markers.
        assert "/*__CSS__*/" not in html
        assert "/*__JS__*/" not in html
        assert "__PAYLOAD__" not in html
        # The embedded payload parses -- the failure that blanks the page.
        _embedded_payload(html)


@pytest.mark.parametrize("profile", ["median", "small"])
def test_size_under_ceiling(tmp_path, profile):
    _emit(profile, tmp_path)
    for name in ("report.presentation.html", "report.working.html"):
        assert (tmp_path / name).stat().st_size < 5 * 1024 * 1024


# -- no composite score, anywhere --------------------------------------------

def test_findings_json_has_no_top_level_score(tmp_path):
    _emit("median", tmp_path)
    findings = json.loads((tmp_path / "findings.json").read_text())
    assert set(findings.keys()) == _FINDINGS_KEYS
    assert "score" not in findings


def test_embedded_payload_has_no_top_level_score(tmp_path):
    _emit("median", tmp_path)
    pres = (tmp_path / "report.presentation.html").read_text(encoding="utf-8")
    payload = _embedded_payload(pres)
    assert "score" not in payload
    assert set(payload.keys()) == _FINDINGS_KEYS


def test_webapp_payload_is_a_subset(tmp_path):
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    payload = webapp_payload(findings)
    # Same top-level shape, strictly fewer keys within.
    assert set(payload.keys()) == _FINDINGS_KEYS
    # The payload drops the formula-bearing security `fields` list entirely.
    assert "fields" not in payload["findings"]["security_exposure"]


# -- two builds from one run -------------------------------------------------

def test_both_builds_emitted_and_logged(tmp_path):
    paths = _emit("median", tmp_path, build="presentation")
    names = [os.path.basename(p) for p in paths]
    assert names == ["findings.json", "report.md", "variants.xlsx",
                     "report.presentation.html", "report.working.html"]
    assert (tmp_path / "report.presentation.html").exists()
    assert (tmp_path / "report.working.html").exists()
    log = (tmp_path / "run.log").read_text()
    assert "builds=working,presentation" in log


def test_working_build_selection_orders_working_first(tmp_path):
    paths = _emit("median", tmp_path, build="working")
    names = [os.path.basename(p) for p in paths]
    assert names.index("report.working.html") < names.index("report.presentation.html")


# -- the metric table and its sort (the persuading artifact) -----------------

def test_definition_multiplicity_sorts_contested_first(tmp_path):
    _emit("median", tmp_path)
    findings = json.loads((tmp_path / "findings.json").read_text())
    groups = findings["findings"]["definition_multiplicity"]["groups"]
    labels = [g["label"] for g in groups]
    # revenue has the most variants (47) but is dominant, so it must NOT lead;
    # a contested group leads instead (build brief section 6).
    assert not groups[0]["dominant"]
    assert labels[-1] == "revenue"
    rev = next(g for g in groups if g["label"] == "revenue")
    assert rev["variant_count"] == 47
    assert rev["dominant"] is True
    ac = next(g for g in groups if g["label"] == "active_customer")
    assert ac["variant_count"] == 14
    assert ac["dominant"] is False


# -- variants.xlsx -----------------------------------------------------------

def test_variants_xlsx_has_a_sheet_per_group(tmp_path):
    _emit("median", tmp_path)
    wb = load_workbook(str(tmp_path / "variants.xlsx"))
    assert "Overview" in wb.sheetnames
    findings = json.loads((tmp_path / "findings.json").read_text())
    groups = findings["findings"]["definition_multiplicity"]["groups"]
    # Overview plus one sheet per group.
    assert len(wb.sheetnames) == len(groups) + 1


# -- report.md ---------------------------------------------------------------

def test_report_md_presentation_omits_formula_working_includes_it():
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    pres_md = render_markdown(redact(findings))
    work_md = render_markdown(mark_working(findings))
    needles = _working_formulas(findings)
    assert needles
    for f in needles:
        assert f not in pres_md
    # The working report carries the variant detail (and thus the formulas).
    assert "Variant detail" in work_md
    assert any(f in work_md for f in needles)


# -- pre-emit secret scan ----------------------------------------------------

def test_assert_no_secrets_flags_a_token():
    poisoned = {"meta": {"note": "Authorization: Bearer abcdef0123456789ABCDEF"}}
    with pytest.raises(SecretLeak):
        assert_no_secrets(poisoned, "working")


def test_emit_aborts_and_writes_nothing_on_secret(tmp_path, monkeypatch):
    store, _config = _scored_store("median")
    real = build_findings(store, "r")
    # Slip a connection-string password into a variant, the kind of thing a
    # future live extract could carry through.
    real["findings"]["definition_multiplicity"]["groups"][0]["variants"][0][
        "resolved_formula"] = "conn: pwd=hunter2 server=db"
    monkeypatch.setattr(emit, "build_findings", lambda s, r: real)
    with pytest.raises(SecretLeak):
        emit_all(store, "r", str(tmp_path))
    # Nothing was written -- the scan runs before any artifact is emitted.
    assert not (tmp_path / "findings.json").exists()
    assert not (tmp_path / "report.presentation.html").exists()


# -- small fixture emits cleanly too -----------------------------------------

def test_small_fixture_emits_all_artifacts(tmp_path):
    paths = _emit("small", tmp_path)
    for p in paths:
        assert os.path.getsize(p) > 0
    assert (tmp_path / "report.md").read_text().strip()


# -- R5: framing-light -------------------------------------------------------
# The same payload with a render flag: no maturity ladder, no scores -- for an
# account that rejects the framing (report web app spec section 8). The
# forbidden vocabulary is the ladder language the light build must never carry;
# it must still carry the three findings and the coverage panel.

# Case-insensitive: any of these is stage/score language and must be absent from
# the light report.md.  "score" is checked as a bare word only, so a metric
# label like "credit_score" in the data is not a false positive.
_LADDER_TOKENS = ("stage", "readiness", "maturity", "binding constraint")


def _report_md(profile, framing):
    store, _config = _scored_store(profile)
    findings = build_findings(store, "r")
    findings["meta"]["framing"] = framing
    return render_markdown(redact(findings))


def test_framing_light_report_md_has_no_ladder_language():
    light = _report_md("median", "light").lower()
    for tok in _LADDER_TOKENS:
        assert tok not in light, "ladder token %r leaked into light report" % tok
    assert not re.search(r"\bscore\b", light), "score language leaked into light"
    # It is still a real report: the three findings and coverage are present.
    assert "definition multiplicity" in light
    assert "security exposure" in light
    assert "retirement" in light
    assert "coverage" in light


def test_full_framing_report_md_keeps_ladder_language():
    # The differential: the same fixture rendered full DOES carry the ladder
    # vocabulary, so the light test above is proving a real omission, not an
    # empty fixture.
    full = _report_md("median", "full").lower()
    assert "readiness" in full
    assert re.search(r"\bscore\b", full)
    assert "stage" in full


@pytest.mark.parametrize("build", ["presentation", "working"])
def test_framing_light_still_no_formula_in_presentation(tmp_path, build):
    # Framing is orthogonal to redaction: the light presentation build must
    # obey the same no-formula / self-contained / offline invariants.
    _emit("median", tmp_path, build=build, framing="light")
    working = json.loads((tmp_path / "findings.json").read_text())
    needles = _working_formulas(working)
    assert needles
    pres = (tmp_path / "report.presentation.html").read_text(encoding="utf-8")
    for formula in needles:
        assert formula not in pres
    for name in ("report.presentation.html", "report.working.html"):
        html = (tmp_path / name).read_text(encoding="utf-8")
        assert "http://" not in html and "https://" not in html
        assert "<link" not in html and "<script src" not in html
        _embedded_payload(html)


def test_framing_light_preserves_contract_keys(tmp_path):
    # A render flag, not a new artifact shape: the top-level key set and the
    # no-composite-score invariant hold exactly as in full framing, and the flag
    # rides inside meta (never as a new top-level key).
    _emit("median", tmp_path, framing="light")
    findings = json.loads((tmp_path / "findings.json").read_text())
    assert set(findings.keys()) == _FINDINGS_KEYS
    assert findings["meta"]["framing"] == "light"
    pres = (tmp_path / "report.presentation.html").read_text(encoding="utf-8")
    payload = _embedded_payload(pres)
    assert set(payload.keys()) == _FINDINGS_KEYS
    assert payload["meta"]["framing"] == "light"


def test_framing_light_recorded_in_run_log(tmp_path):
    _emit("median", tmp_path, framing="light")
    assert "framing=light" in (tmp_path / "run.log").read_text()


def test_emit_rejects_unknown_framing(tmp_path):
    store, _config = _scored_store("median")
    with pytest.raises(ValueError):
        emit_all(store, "r", str(tmp_path), framing="ladder")


# -- R5: multi-run comparison ------------------------------------------------
# Two findings.json of one account over time. The versioned query set is why a
# moved number can be attributed to an estate change vs a definition change.

def _two_runs():
    store, _config = _scored_store("median")
    baseline = build_findings(store, "r")
    current = copy.deepcopy(baseline)
    # A later run of the same site, same query set: one estate number moved.
    current["meta"]["run_id"] = "r2"
    rt = current["findings"]["retirement"]
    rt["zero_view_workbooks"] = rt.get("zero_view_workbooks", 0) + 3
    return baseline, current


def test_comparison_flags_a_moved_number_as_estate_change():
    baseline, current = _two_runs()
    delta = compare_runs(baseline, current)
    assert delta["comparable"] is True
    assert delta["warnings"] == []
    rows = delta["findings"]["retirement"]
    zvw = next(r for r in rows if r["key"] == "zero_view_workbooks")
    assert zvw["delta"] == 3
    md = render_comparison_markdown(delta)
    assert "Zero-view workbooks" in md
    assert "+3" in md
    # No composite score is compared -- the footer says so and no `score` column
    # is emitted.
    assert "No composite score is compared" in md


def test_comparison_warns_when_query_set_changed():
    baseline, current = _two_runs()
    # A changed query set means a moved number may be a changed definition, not a
    # changed estate: the comparison must say so and stop calling it like-for-like.
    current["meta"]["query_set_version"] = "v2"
    delta = compare_runs(baseline, current)
    assert delta["comparable"] is False
    assert any("query set" in w for w in delta["warnings"])
    md = render_comparison_markdown(delta)
    assert "not a clean like-for-like delta" in md
    assert "query set changed" in md


def test_comparison_warns_when_site_differs():
    baseline, current = _two_runs()
    current["meta"]["site_name"] = "a different site"
    delta = compare_runs(baseline, current)
    assert delta["comparable"] is False
    assert any("site differs" in w for w in delta["warnings"])
