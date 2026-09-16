"""report.md -- the customer-facing readiness report (build spec section 11).

The front page assembles from the three findings; coverage gaps render as their
own section so an unmeasured dimension is never mistaken for a clean one. No
composite score anywhere: the register names the binding constraint per domain.

Rendered from whichever build (working or presentation) it is handed, so the
presentation report.md inherits the same redaction as the web app.
"""

from typing import List

_STAGE_NAMES = {
    1: "Minimal", 2: "Emerging", 3: "Performing",
    4: "Optimizing", 5: "Leading", 6: "Autonomous",
}


def render_markdown(findings):
    # type: (dict) -> str
    meta = findings.get("meta", {})
    # Framing-light (report web app spec section 8): present the same findings,
    # coverage, and evidence with no stage/readiness/score language for accounts
    # that reject a maturity ladder. It is a render flag on one payload -- the
    # cover, facet table, and register (the only stage/score-bearing sections)
    # are simply omitted; the findings and coverage sections carry no ladder
    # language and render identically either way.
    light = meta.get("framing") == "light"
    lines = []  # type: List[str]
    a = lines.append

    build = meta.get("build", "working")
    a("# Tableau Estate Scan" if light else "# Tableau Estate Readiness")
    a("")
    if build == "working":
        a("> **Working build.** Contains business logic (resolved formulas) "
          "and owner names. Stays with the analytics team.")
    else:
        a("> **Presentation build.** Counts, rankings, and disagreement "
          "figures only. No formula text or individual owner names.")
    a("")
    a("- Site: %s" % (meta.get("site_name") or "unknown"))
    a("- Scan window: %s to %s"
      % (meta.get("scan_started_at") or "?", meta.get("scan_completed_at") or "?"))
    a("- Tool %s, query set %s, app template %s"
      % (meta.get("tool_version"), meta.get("query_set_version"),
         meta.get("app_template_version")))
    a("- Grouping: %s   Adoption source: %s"
      % (meta.get("grouping_mode"), meta.get("adoption_source")))
    a("")

    if not light:
        _cover(a, findings)
    _finding_definitions(a, findings, build)
    _finding_security(a, findings)
    _finding_retirement(a, findings)
    _finding_governance(a, findings)
    if not light:
        _dimensions(a, findings)
        _register(a, findings)
    _coverage(a, findings)

    a("")
    a("---")
    if light:
        a("_Findings-only build. The figures above are drawn directly from the "
          "scan of the estate; no ranking or rating is applied._")
    else:
        a("_No composite maturity score is emitted. Readiness is the binding "
          "constraint per domain; averaging would hide it._")
    a("")
    return "\n".join(lines)


def _stage(n):
    # type: (object) -> str
    if n is None:
        return "unscored"
    return "%s (%s)" % (n, _STAGE_NAMES.get(n, "?"))


def _cover(a, findings):
    domains = findings.get("domains", [])
    if not domains:
        return
    a("## Cover")
    a("")
    for d in domains:
        binding = ", ".join(d.get("binding_constraints", [])) or "none"
        a("- **%s** — current stage %s, target %s, binding constraint: %s "
          "(confidence: %s)"
          % (d["id"], _stage(d.get("readiness")), _stage(d.get("target_stage")),
             binding, d.get("confidence")))
    a("")


# How the per-group dominance state renders in the "Dominant" column. A singular
# concept has one definition, so "no dominant variant" would misread as a
# contest; it shows "—". An unmeasured concept has >=2 definitions but usage was
# not measured, so dominance is unknown, not absent.
_DOMINANCE_CELL = {
    "dominant": "yes",
    "contested": "**no**",
    "unmeasured": "unmeasured",
    "singular": "—",
}


def _finding_definitions(a, findings, build):
    dm = findings.get("findings", {}).get("definition_multiplicity", {})
    groups = dm.get("groups", [])
    multiplicity = dm.get("multiplicity_group_count", 0)
    a("## Finding 1 — Definition multiplicity")
    a("")
    a("%d metric concept(s) in scope; %d defined more than once."
      % (len(groups), multiplicity))
    if multiplicity:
        if dm.get("usage_measured", True):
            a("%d of those show no dominant variant (contested)."
              % dm.get("contested_group_count", 0))
        else:
            a("Which variant dominates was not measured this run (usage_events "
              "unavailable), so contest cannot be determined — see the coverage "
              "section. A concept here is multiply-defined, not shown as "
              "contested.")
    a("")
    a("| Metric | Variants | Workbooks | Disagreeing | Cover 80% | Dominant |")
    a("|---|--:|--:|--:|--:|:--:|")
    for g in groups:
        a("| %s | %d | %d | %d | %d | %s |"
          % (g["label"], g["variant_count"], g["workbooks_affected"],
             g["disagreeing_variants"], g["variants_covering_80pct_views"],
             _DOMINANCE_CELL.get(g.get("dominance"),
                                 "yes" if g.get("dominant") else "**no**")))
    a("")
    a("_A single-definition concept is not multiplicity; it shows \"—\". Sorted "
      "so a contested concept — the harder adjudication — leads._")
    a("")
    if build == "working":
        _variant_detail(a, groups)


def _variant_detail(a, groups):
    # Detail for every multiply-defined concept (>=2 variants). Which one wins is
    # a usage question the table above already answers; the detail is the
    # side-by-side an analyst adjudicates from, so it is useful whether the
    # concept is contested, settled, or its dominance unmeasured.
    multi = [g for g in groups if g.get("multiplicity")]
    if not multi:
        return
    a("### Variant detail (concepts with multiple definitions)")
    a("")
    for g in multi:
        a("#### %s" % g["label"])
        a("")
        for v in g["variants"]:
            marker = " *(rank 1)*" if v["usage_rank"] == 1 else ""
            a("- **%s**%s — %d views (%.0f%%), %d workbooks, owner: %s, source: %s"
              % (v["field_name"], marker, v["view_count"],
                 100.0 * v["view_share"], v["workbook_count"],
                 v.get("owner") or "?", v.get("datasource_name") or "?"))
            if v.get("resolved_formula"):
                a("  - `%s`" % v["resolved_formula"])
        a("")


def _finding_security(a, findings):
    sec = findings.get("findings", {}).get("security_exposure", {})
    a("## Finding 2 — Security exposure")
    a("")
    a("%d calculated field(s) enforce access in the visualization layer, "
      "across %d workbook(s)."
      % (sec.get("user_context_field_count", 0),
         sec.get("affected_workbook_count", 0)))
    a("")
    a("A programmatic query against the data source bypasses a rule enforced "
      "only in a calculated field. Row-level entitlement belongs at the "
      "source, not in the view.")
    a("")


def _finding_retirement(a, findings):
    r = findings.get("findings", {}).get("retirement", {})
    a("## Finding 3 — Retirement case")
    a("")
    total = r.get("workbooks_total", 0)
    if r.get("usage_measured", True):
        zero = r.get("zero_view_workbooks", 0)
        a("- %d of %d workbooks drew no views in the window (recoverable capacity)."
          % (zero, total))
        a("- %d workbook(s) carry 80%% of all views (%d total views)."
          % (r.get("workbooks_covering_80pct_views", 0), r.get("total_views", 0)))
    else:
        a("- Workbook view data was not measured for this run (usage_events "
          "unavailable), so view-based retirement candidates cannot be assessed. "
          "Zero views here means *not measured*, not *unused* — see the coverage "
          "panel.")
    a("- %d upstream table(s) feed more than one published source "
      "(max %d sources on one table) — candidate consolidation."
      % (r.get("redundant_source_tables", 0), r.get("max_sources_per_table", 0)))
    a("")


_MECH_LABEL = {"certification": "Certification",
               "data_quality_warnings": "Data-quality warnings",
               "permission_grants": "Permission grants",
               "explicit_deny": "Explicit Deny rules"}
_STATUS_LABEL = {"in_use": "in use", "not_exercised": "not exercised",
                 "unmeasured": "not measured"}


def _mech_detail(m):
    # type: (dict) -> str
    if not m.get("measured"):
        return "feed not measured this run"
    if m["mechanism"] == "certification":
        return "%s of %s published sources certified" % (
            m.get("certified_sources"), m.get("published_sources"))
    if m["mechanism"] == "data_quality_warnings":
        return "%s warning(s), %s active" % (
            m.get("warnings_total"), m.get("warnings_active"))
    if m["mechanism"] == "permission_grants":
        return "%s grant(s) across %s object(s)" % (
            m.get("grants_total"), m.get("objects_covered"))
    if m["mechanism"] == "explicit_deny":
        return "%s explicit Deny rule(s)" % m.get("deny_rules")
    return "—"


def _finding_governance(a, findings):
    # Observed-presence evidence, not a score: renders identically in the
    # framing-light build (it carries no stage/ladder language). It proves a
    # governance mechanism is in place and hands the interview good/bad examples;
    # it adjusts no maturity gate, so it sits with the findings, not the register.
    gp = findings.get("findings", {}).get("governance_posture", {})
    arcs = gp.get("arcs", [])
    if not arcs:
        return
    a("## Finding 4 — Governance posture (observed presence)")
    a("")
    a("Observed presence of governance mechanisms — proof a mechanism is in "
      "place and exercised, with good and bad examples for the interview to "
      "probe. Observed by the scan, assessed by the interview: evidence only, "
      "never a rating.")
    a("")
    for arc in arcs:
        a("### %s arc — observed, assessed by interview"
          % arc.get("arc", "?").capitalize())
        a("")
        a("| Mechanism | Status | Detail |")
        a("|---|---|---|")
        for m in arc.get("mechanisms", []):
            a("| %s | %s | %s |"
              % (_MECH_LABEL.get(m["mechanism"], m["mechanism"]),
                 _STATUS_LABEL.get(m.get("status"), m.get("status")),
                 _mech_detail(m)))
        a("")
        # Each arc carries one contrast block: the detective arc a
        # certification/DQW divergence, the preventive arc a permission exposure.
        if "divergence" in arc:
            _governance_divergence(a, arc.get("divergence", {}))
        if "exposure" in arc:
            _governance_exposure(a, arc.get("exposure", {}))


def _governance_divergence(a, dv):
    if not dv.get("measured"):
        a("_Certification/data-quality divergence not measured this run "
          "(a required feed was unavailable — see the coverage panel). No "
          "divergence is asserted; absence of measurement is not agreement._")
        a("")
        return
    count = dv.get("count", 0)
    a("**Certification vs data-quality divergence** — %d certified source(s) "
      "carry an active data-quality warning: the trust signal (certification) "
      "disagrees with the health signal (the live warning)." % count)
    a("")
    bad = dv.get("bad_examples", [])
    if bad:
        a("Certified but warned (dig here — what slipped past certification?):")
        for e in bad:
            sev = " *(elevated)*" if e.get("is_elevated") else ""
            a("- %s — %s%s"
              % (e.get("datasource_name"), e.get("warning_type") or "warning", sev))
        a("")
    good = dv.get("good_examples", [])
    if good:
        a("Certified and clean (what good looks like):")
        for e in good:
            a("- %s" % e.get("datasource_name"))
        a("")


def _governance_exposure(a, ex):
    if not ex.get("measured"):
        a("_Permission exposure not measured this run (the permissions feed was "
          "unavailable -- see the coverage panel). No exposure is asserted; "
          "absence of measurement is not a clean bill._")
        a("")
        return
    count = ex.get("count", 0)
    a("**Permission exposure** -- %d grant(s) hand a sensitive capability to an "
      "everyone-group: broad access where the model should be scoped." % count)
    a("")
    bad = ex.get("bad_examples", [])
    if bad:
        a("Broad and powerful (dig here -- who can change or delete widely?):")
        for e in bad:
            a("- %s -- %s on %s"
              % (e.get("grantee"), e.get("capability"), e.get("object_type")))
        a("")
    good = ex.get("good_examples", [])
    if good:
        a("Scoped to a named group (what good looks like):")
        for e in good:
            a("- %s -- %s on %s"
              % (e.get("grantee"), e.get("capability"), e.get("object_type")))
        a("")


def _dimensions(a, findings):
    facets = findings.get("facets", [])
    if not facets:
        return
    a("## Readiness by facet")
    a("")
    a("| Facet | Dimension | Score | Evidence | Gates |")
    a("|---|---|--:|---|---|")
    for f in facets:
        gates = ", ".join(str(g) for g in f.get("gates", [])) or "—"
        a("| %s | %s | %s | %s | %s |"
          % (f["id"], f.get("dimension"), f["score"],
             f.get("evidence") or f.get("confidence"), gates))
    a("")


def _register(a, findings):
    domains = findings.get("domains", [])
    if not domains:
        return
    a("## Readiness register")
    a("")
    a("| Domain | Target | Current | Gap | Binding constraint | Confidence |")
    a("|---|--:|--:|--:|---|---|")
    for d in domains:
        binding = ", ".join(d.get("binding_constraints", [])) or "none"
        a("| %s | %s | %s | %s | %s | %s |"
          % (d["id"], _stage(d.get("target_stage")), _stage(d.get("readiness")),
             d.get("gap"), binding, d.get("confidence")))
    a("")
    for d in domains:
        unscored = d.get("unscored_dimensions", [])
        if unscored:
            a("- **%s** unscored dimensions: %s"
              % (d["id"], ", ".join(unscored)))
    a("")


def _coverage(a, findings):
    coverage = findings.get("coverage", [])
    gaps = [c for c in coverage if c["status"] != "ok"]
    a("## Coverage")
    a("")
    if not coverage:
        a("_No coverage records._")
        a("")
        return
    a("%d measure(s) attempted, %d with gaps. An unmeasured dimension is not a "
      "clean one." % (len(coverage), len(gaps)))
    a("")
    if gaps:
        a("| Measure | Status | Reason |")
        a("|---|---|---|")
        for c in gaps:
            a("| %s | %s | %s |" % (c["measure"], c["status"],
                                    c["reason"] or ""))
        a("")
