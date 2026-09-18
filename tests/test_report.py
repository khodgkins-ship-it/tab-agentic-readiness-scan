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
from estate_scan.report.emit import emit_all
from estate_scan.report.findings import _definition_multiplicity, build_findings
from estate_scan.report.labels import dimension_name, facet_name
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


# -- internal codes never surface to the reader ------------------------------
# A consumer of the report has no idea what "SEM-03" or "semantic.describability"
# means, so the internal identifiers stay join-keys-only: the reader sees the
# name/description from labels.py, never the bare code.

# The flag catalog codes (SEM-03, DF-01, GOV-03, ...) as they appear in text.
_FLAG_CODE_RE = re.compile(r"\b[A-Z]{2,3}-\d{2}\b")


def test_markdown_shows_names_not_codes(tmp_path):
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    md = render_markdown(findings)

    facet_ids = {f["id"] for f in findings["facets"]}
    assert facet_ids, "fixture should score some facets to make this meaningful"
    for fid in facet_ids:
        # the dotted facet code is a join key only -- never rendered
        assert fid not in md, "facet code %r leaked into the report" % fid
        assert facet_name(fid) in md, \
            "facet name for %r missing from the report" % fid

    # no flag catalog code (markdown surfaces flags only through their findings)
    assert not _FLAG_CODE_RE.search(md), \
        "a flag catalog code (e.g. SEM-03) appeared in the report"

    # unscored dimensions render as names, never the snake_case code
    for d in findings["domains"]:
        for dim in d.get("unscored_dimensions", []):
            if "_" in dim:                 # e.g. action_surface, operating_model
                assert dim not in md, "dimension code %r leaked" % dim
            assert dimension_name(dim) in md


def test_webapp_payload_carries_labels_not_bare_codes(tmp_path):
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    payload = webapp_payload(findings)

    # Every facet the app renders carries a human name + description; the raw
    # dotted id stays only as the join key the app matches on.
    assert payload["facets"], "fixture should score some facets"
    for f in payload["facets"]:
        assert f["name"] and f["name"] != f["id"]
        assert f["name"] == facet_name(f["id"])
        assert f["description"]
        assert f["dimension_label"] == dimension_name(f["dimension"])

    # Every flag the app renders carries a human name, never the catalog code.
    assert payload["flags"], "fixture should fire some flags"
    for fl in payload["flags"]:
        assert fl["name"] and fl["name"] != fl["id"]
        assert not _FLAG_CODE_RE.match(fl["name"])
        assert fl["description"]

    # Binding-constraint and unscored-dimension display lists stay aligned with
    # their join-key lists and carry names, not the dotted/underscore codes.
    for d in payload["domains"]:
        assert len(d["binding_constraint_labels"]) == len(d["binding_constraints"])
        assert all("." not in label for label in d["binding_constraint_labels"])
        assert len(d["unscored_dimension_labels"]) == len(d["unscored_dimensions"])
        assert all("_" not in label for label in d["unscored_dimension_labels"])


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
    # Concept-level grouping: each core metric is ONE row -- "defined N ways" --
    # not one row per formula shape. The multiplicity findings are the concepts
    # carrying >=2 definitions. The persuading-artifact invariant holds: a
    # contested concept (no dominant definition) leads and no dominant one does
    # (build brief section 6).
    multiplicity = [g for g in groups if g["multiplicity"]]
    assert multiplicity[0]["dominance"] == "contested"
    assert not multiplicity[0]["dominant"]
    # The sort is a clean partition: all contested concepts precede all dominant
    # ones (singular concepts, one definition, are not multiplicity findings).
    rank = {"contested": 0, "dominant": 1}
    order = [rank[g["dominance"]] for g in multiplicity]
    assert order == sorted(order)

    # Revenue is a SINGLE concept, defined eight ways across 45 fields. Usage has
    # settled on one definition, so the concept is dominant -- and, being
    # dominant, it never leads the table.
    rev_groups = [g for g in multiplicity if g["label"] == "revenue"]
    assert len(rev_groups) == 1
    rev = rev_groups[0]
    assert rev["definition_count"] == 8
    assert rev["variant_count"] == 45
    assert rev["dominance"] == "dominant"
    assert rev is not multiplicity[0]

    # active_customer is a SINGLE contested concept: several definitions, none
    # settled -- the governance problem the backlog surfaces first.
    ac_groups = [g for g in multiplicity if g["label"] == "active_customer"]
    assert len(ac_groups) == 1
    assert ac_groups[0]["dominance"] == "contested"


# -- Finding 1 dominance state machine: singular / contested / dominant ------
# A group is only a multiplicity finding when it carries >=2 definitions. A
# single-definition concept is `singular` (nothing to adjudicate), not
# `contested`, and drops out of the multiplicity and contested tallies. These
# four states drive every artifact's Dominant column, so they are pinned here
# with a hand-built store that exercises each in one measured run.

def _variant_row(field_id, name, views, is_dominant, rank,
                 formula="SUM([Sales])"):
    return {
        "field_id": field_id,
        "field_name": name,
        "view_count": views,
        "workbook_count": 1,
        # distinct definitions -> the group reads as genuinely disagreeing.
        # definition_key is what multiplicity/dominance is decided over now; one
        # per field here so each field is its own definition.
        "normalized_hash": "h_%s" % field_id,
        "definition_key": "d_%s" % field_id,
        "is_dominant": is_dominant,
        "usage_rank": rank,
        "resolution_status": "resolved",
        "resolved_formula": formula,
        "owner": "an owner",
        "datasource_name": "a source",
    }


class _FakeStore:
    """The minimal read surface `_definition_multiplicity` touches, so the
    dominance state machine can be driven directly without the whole pipeline.
    `groups` is a list of {group_id, label, variants}."""

    def __init__(self, usage_status, groups):
        self._usage = usage_status
        self._order = [g["group_id"] for g in groups]
        self._groups = {g["group_id"]: g for g in groups}

    def coverage_status(self, run_id, measure):
        return self._usage if measure == "usage_events" else "ok"

    def metric_groups(self, run_id):
        return [{"group_id": gid,
                 "canonical_label": self._groups[gid]["label"],
                 "method": "formula_signature", "confidence": "medium"}
                for gid in self._order]

    def group_variant_detail(self, run_id, gid):
        return list(self._groups[gid]["variants"])

    def metric_variants(self, run_id, gid):
        return list(self._groups[gid]["variants"])

    def group_workbook_count(self, run_id, gid):
        return sum(v["workbook_count"] for v in self._groups[gid]["variants"])

    def variant_execution_detail(self, run_id, gid):
        return []


def _four_state_store(usage_status="ok"):
    return _FakeStore(usage_status, [
        # one definition: singular, not a multiplicity finding
        {"group_id": "grp_solo", "label": "solo_metric",
         "variants": [_variant_row("f_solo", "Solo", 10, 1, 1)]},
        # two definitions, none dominant: contested
        {"group_id": "grp_split", "label": "split_metric",
         "variants": [_variant_row("f_a", "A", 5, 0, 1),
                      _variant_row("f_b", "B", 4, 0, 2)]},
        # two definitions, one dominant: settled
        {"group_id": "grp_won", "label": "won_metric",
         "variants": [_variant_row("f_c", "C", 100, 1, 1),
                      _variant_row("f_d", "D", 1, 0, 2)]},
    ])


def test_single_variant_concept_is_singular_not_contested():
    dm = _definition_multiplicity(_four_state_store("ok"), "r")
    assert dm["usage_measured"] is True
    by_label = {g["label"]: g for g in dm["groups"]}

    solo = by_label["solo_metric"]
    assert solo["variant_count"] == 1
    assert solo["multiplicity"] is False
    assert solo["dominance"] == "singular"
    # trivially "dominant" in the ranker's sense, but the finding never reports a
    # one-definition concept as dominant -- it is simply singular.
    assert solo["dominant"] is False

    assert by_label["split_metric"]["dominance"] == "contested"
    assert by_label["won_metric"]["dominance"] == "dominant"

    # tallies count only the >=2-definition concepts; the singular one drops out.
    assert dm["multiplicity_group_count"] == 2
    assert dm["contested_group_count"] == 1

    # sort: the contested concept (hardest adjudication) leads; singular last.
    order = [g["label"] for g in dm["groups"]]
    assert order[0] == "split_metric"
    assert order[-1] == "solo_metric"


def test_singular_concept_excluded_from_table_and_variant_detail():
    dm = _definition_multiplicity(_four_state_store("ok"), "r")
    findings = {
        "meta": {"build": "working"},
        "facets": [], "domains": [], "coverage": [],
        "findings": {"definition_multiplicity": dm,
                     "security_exposure": {}, "retirement": {}},
    }
    md = render_markdown(findings)
    # The census lede still counts the singular concept "in scope".
    assert "3 metric concept(s) in scope; 2 defined more than once." in md
    # measured run: the contested count is asserted, dominance is not "unmeasured"
    assert "1 of those show no dominant variant (contested)." in md
    assert "unmeasured" not in md
    # The table lists only multiply-defined concepts; the single-definition one
    # (no variant to adjudicate) is not a row at all -- it never appears.
    assert "| split_metric |" in md
    assert "| won_metric |" in md
    assert "solo_metric" not in md
    # variant detail is likewise only for the multiply-defined concepts.
    assert "#### split_metric" in md
    assert "#### won_metric" in md
    assert "#### solo_metric" not in md


def test_definition_multiplicity_unmeasured_usage_is_not_contested():
    """Plan invariant 7 for Finding 1: dominance is usage-derived, so with
    usage_events not `ok` a multiply-defined concept is `unmeasured`, never
    `contested`. Multiplicity itself -- how many concepts carry >=2 definitions
    -- is structural and stays determinable."""
    store, _config = _scored_store("median")
    measured = build_findings(store, "r")["findings"]["definition_multiplicity"]
    assert measured["usage_measured"] is True
    baseline_multiplicity = measured["multiplicity_group_count"]
    assert baseline_multiplicity >= 1

    store.record_coverage("r", "usage_events", "failed", "REST status 501")
    dm = build_findings(store, "r")["findings"]["definition_multiplicity"]
    assert dm["usage_measured"] is False
    # structural multiplicity is unchanged when usage goes unmeasured
    assert dm["multiplicity_group_count"] == baseline_multiplicity
    # a contest we cannot see is never asserted
    assert dm["contested_group_count"] == 0
    for g in dm["groups"]:
        if g["multiplicity"]:
            assert g["dominance"] == "unmeasured"
            assert g["dominant"] is False

    md = render_markdown(build_findings(store, "r")).lower()
    assert "not measured this run" in md
    # the headline must not claim any concept is contested when we could not see
    assert "(contested)" not in md


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


# -- coverage honesty: retirement finding degrades when usage unmeasured -----

def test_retirement_measured_on_fixture():
    # Differential control: on the fixture usage_events is `ok`, so the finding
    # carries real view figures and the markdown makes the recoverable-capacity
    # claim. This is what the unmeasured case below must NOT do.
    store, _config = _scored_store("median")
    r = build_findings(store, "r")["findings"]["retirement"]
    assert r["usage_measured"] is True
    assert r["zero_view_workbooks"] is not None
    md = render_markdown(build_findings(store, "r")).lower()
    assert "drew no views" in md


def test_retirement_degrades_when_usage_events_not_ok():
    """Plan invariant 7 on the reporting side: with usage_events not `ok`, the
    retirement finding must null its view-derived fields and flag itself
    unmeasured, and the markdown must say the data was not measured rather than
    claim workbooks "drew no views". The lineage/fanout signal stays real."""
    store, _config = _scored_store("median")
    store.record_coverage("r", "usage_events", "failed", "REST status 501")

    findings = build_findings(store, "r")
    r = findings["findings"]["retirement"]
    assert r["usage_measured"] is False
    assert r["zero_view_workbooks"] is None
    assert r["total_views"] is None
    assert r["workbooks_covering_80pct_views"] is None
    assert r["unused_workbook_sample"] == []
    # The always-real lineage signal is still present.
    assert r["workbooks_total"] is not None
    assert "redundant_source_tables" in r

    md = render_markdown(findings).lower()
    assert "not measured" in md
    assert "drew no views" not in md
    # Consolidation (from lineage) is still reported.
    assert "candidate consolidation" in md


# -- Finding 4: governance posture (observed presence evidence, non-gating) ---
# The third governance-signal category (build plan R4). The scored arcs
# (accountability, assurance) gate the maturity loop from ownership/certification
# coverage; this block does NOT gate -- it proves a detective mechanism is in
# place and exercised and hands the interview concrete good/bad examples. Coverage
# is first-class: an unmeasured feed reads `unmeasured`, never `not_exercised`.

def _detective(findings):
    arcs = findings["findings"]["governance_posture"]["arcs"]
    return next(a for a in arcs if a["arc"] == "detective")


def test_governance_posture_presence_evidence_assembled():
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    det = _detective(findings)
    # The arc is assessed by the interview, not scored from these signals.
    assert det["scored_by"] == "interview"
    mech = {m["mechanism"]: m for m in det["mechanisms"]}
    # Both detective mechanisms are measured and exercised on the fixture.
    assert mech["certification"]["status"] == "in_use"
    assert mech["certification"]["certified_sources"] == 46
    assert mech["certification"]["published_sources"] == 200
    assert mech["data_quality_warnings"]["status"] == "in_use"
    assert mech["data_quality_warnings"]["warnings_total"] > 0
    # Divergence set = distinct certified sources carrying an active warning
    # (the GOV-03 set), with clean certified sources as the good examples.
    dv = det["divergence"]
    assert dv["measured"] is True
    assert dv["count"] == len(dv["bad_examples"]) == 5
    assert dv["good_examples"], "certified-clean sources are the good examples"
    gov03 = {r["name"] for r in store.certified_sources_with_active_warning("r")}
    assert {e["datasource_name"] for e in dv["bad_examples"]} == gov03


def test_governance_posture_marks_unmeasured_feed_honestly():
    """Coverage first-class on the evidence side: with the DQW feed not `ok`, the
    data-quality mechanism reads `unmeasured` (never `not_exercised`) and the
    divergence is not asserted, while the still-measured certification mechanism
    is untouched. Absence of measurement is not absence of the mechanism."""
    store, _config = _scored_store("median")
    store.record_coverage("r", "data_quality_warnings", "failed", "GraphQL 500")
    findings = build_findings(store, "r")
    det = _detective(findings)
    mech = {m["mechanism"]: m for m in det["mechanisms"]}
    dqw = mech["data_quality_warnings"]
    assert dqw["measured"] is False
    assert dqw["status"] == "unmeasured"
    assert dqw["warnings_total"] is None and dqw["warnings_active"] is None
    # Divergence needs both feeds; unmeasured is reported honestly, not as zero.
    dv = det["divergence"]
    assert dv["measured"] is False
    assert dv["count"] is None
    assert dv["bad_examples"] == [] and dv["good_examples"] == []
    # The still-measured certification mechanism is unaffected.
    assert mech["certification"]["status"] == "in_use"
    # And the markdown says so rather than implying agreement.
    md = render_markdown(findings).lower()
    assert "divergence not measured this run" in md


def test_governance_posture_does_not_score_the_detective_arc():
    """Observed presence is evidence, not a score: it mints no scored
    governance.detective facet and does not move the maturity register. The
    detective arc stays the interview's to set, and the no-composite contract
    holds with the block present."""
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    facet_ids = {f["id"] for f in findings["facets"]}
    assert "governance.detective" not in facet_ids
    assert _detective(findings)["scored_by"] == "interview"
    assert set(findings.keys()) == _FINDINGS_KEYS


def test_governance_posture_survives_redaction_without_owner_names():
    """Source names and counts only -- no owner names -- so the block passes
    through both redaction builds untouched and leaks nothing into the
    presentation build or the pre-emit secret scan."""
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    gp = findings["findings"]["governance_posture"]
    # redact() mutates only definition_multiplicity/security_exposure; the
    # governance block is deep-equal in the presentation copy.
    assert redact(findings)["findings"]["governance_posture"] == gp
    # No owner key anywhere in the block (belt-and-braces on the no-owner rule).
    assert "owner" not in json.dumps(gp)
    # It survives the pre-emit secret scan in both builds.
    assert_no_secrets(redact(findings), "presentation")
    assert_no_secrets(mark_working(findings), "working")


def test_governance_posture_in_payload_and_markdown():
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    payload = webapp_payload(findings)
    # Carried in the strict-subset payload, same top-level shape, no owner key.
    gp = payload["findings"]["governance_posture"]
    det = next(a for a in gp["arcs"] if a["arc"] == "detective")
    assert det["scored_by"] == "interview"
    assert "owner" not in json.dumps(gp)
    assert set(payload.keys()) == _FINDINGS_KEYS
    # Markdown renders it as observed-but-interview-assessed evidence with
    # concrete good/bad examples.
    md = render_markdown(findings).lower()
    assert "governance posture" in md
    assert "assessed by the interview" in md
    assert "certified but warned" in md


# The preventive arc is the second observed-presence arc (build plan R4): the
# same non-gating pattern over the permissions feed. It proves the access model
# is exercised (grants recorded, explicit Deny in use) and hands the interview
# broad-and-powerful vs scoped grants as examples. SEC-02 the flag scores
# permissive-grant firing separately; this block never gates. Coverage stays
# first-class; good examples are group grantees only, so no user name can leak.

def _preventive(findings):
    arcs = findings["findings"]["governance_posture"]["arcs"]
    return next(a for a in arcs if a["arc"] == "preventive")


def test_governance_posture_preventive_arc_assembled():
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    arcs = findings["findings"]["governance_posture"]["arcs"]
    # Ordered as the governance loop activates: preventive before detective.
    assert [a["arc"] for a in arcs] == ["preventive", "detective"]
    prev = _preventive(findings)
    assert prev["scored_by"] == "interview"
    mech = {m["mechanism"]: m for m in prev["mechanisms"]}
    total, objects, deny = store.permission_grant_counts("r")
    assert mech["permission_grants"]["status"] == "in_use"
    assert mech["permission_grants"]["grants_total"] == total
    assert mech["permission_grants"]["objects_covered"] == objects
    assert mech["explicit_deny"]["status"] == "in_use"
    assert mech["explicit_deny"]["deny_rules"] == deny
    # Shipped rules: AllUsers holds only [Read], so there is no permissive grant
    # (count 0) -- good posture. Analysts (a NAMED group) holds Write, so the
    # scoped grant is the good example. Fixture is NOT shaped to make it fire.
    ex = prev["exposure"]
    assert ex["measured"] is True
    assert ex["count"] == 0 and ex["bad_examples"] == []
    assert ex["good_examples"], "scoped sensitive grants are the good examples"
    assert all(e["grantee"] == "Analysts" for e in ex["good_examples"])


def test_governance_posture_preventive_exposure_reports_a_permissive_grant():
    """The bad path, proven without shaping the fixture: inject one permissive
    grant (AllUsers may Delete) and a user-scoped sensitive grant. The exposure
    block reports the broad grant, and the user grant never appears -- good
    examples are group grantees only, so no user name leaks."""
    store, _config = _scored_store("median")
    store.load_permissions("r", [
        {"object_type": "workbook", "object_id": "wb_open",
         "grantee_type": "group", "grantee_id": "AllUsers",
         "capability": "Delete", "mode": "Allow", "sampled": 0},
        {"object_type": "workbook", "object_id": "wb_user",
         "grantee_type": "user", "grantee_id": "jsmith",
         "capability": "Write", "mode": "Allow", "sampled": 1}])
    findings = build_findings(store, "r")
    ex = _preventive(findings)["exposure"]
    assert ex["count"] == 1
    bad = ex["bad_examples"]
    assert len(bad) == 1
    assert bad[0]["grantee"] == "AllUsers" and bad[0]["capability"] == "Delete"
    assert bad[0]["object_type"] == "workbook"
    # The user-scoped grant is excluded from good examples (group grantees only)
    # and its username appears nowhere in the block.
    gp = findings["findings"]["governance_posture"]
    assert all(e["grantee"] != "jsmith" for e in ex["good_examples"])
    assert "jsmith" not in json.dumps(gp)
    md = render_markdown(findings).lower()
    assert "broad and powerful" in md


def test_governance_posture_preventive_marks_unmeasured_feed_honestly():
    """Coverage first-class on the preventive side: with the permissions feed not
    `ok`, both mechanisms read `unmeasured` (never `not_exercised`) and no
    exposure is asserted. Absence of measurement is not a clean bill."""
    store, _config = _scored_store("median")
    store.record_coverage("r", "permissions", "failed", "REST 403")
    findings = build_findings(store, "r")
    prev = _preventive(findings)
    mech = {m["mechanism"]: m for m in prev["mechanisms"]}
    assert mech["permission_grants"]["measured"] is False
    assert mech["permission_grants"]["status"] == "unmeasured"
    assert mech["permission_grants"]["grants_total"] is None
    assert mech["explicit_deny"]["status"] == "unmeasured"
    assert mech["explicit_deny"]["deny_rules"] is None
    ex = prev["exposure"]
    assert ex["measured"] is False and ex["count"] is None
    assert ex["bad_examples"] == [] and ex["good_examples"] == []
    md = render_markdown(findings).lower()
    assert "permission exposure not measured this run" in md


def test_governance_posture_preventive_does_not_score_and_lands_in_payload():
    """Observed presence, not a score: it mints no scored governance.preventive
    facet, the arc stays the interview's to set, the no-composite contract holds,
    and the projected payload carries the exposure block with no owner name."""
    store, _config = _scored_store("median")
    findings = build_findings(store, "r")
    facet_ids = {f["id"] for f in findings["facets"]}
    assert "governance.preventive" not in facet_ids
    assert _preventive(findings)["scored_by"] == "interview"
    assert set(findings.keys()) == _FINDINGS_KEYS
    payload = webapp_payload(findings)
    prev = next(a for a in payload["findings"]["governance_posture"]["arcs"]
                if a["arc"] == "preventive")
    assert prev["exposure"]["measured"] is True
    assert "divergence" not in prev  # only the arc's own contrast block
    assert "owner" not in json.dumps(payload["findings"]["governance_posture"])
    assert set(payload.keys()) == _FINDINGS_KEYS
