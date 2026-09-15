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


def _finding_definitions(a, findings, build):
    dm = findings.get("findings", {}).get("definition_multiplicity", {})
    groups = dm.get("groups", [])
    a("## Finding 1 — Definition multiplicity")
    a("")
    a("%d metric group(s), %d with no dominant variant."
      % (len(groups), dm.get("contested_group_count", 0)))
    a("")
    a("| Metric | Variants | Workbooks | Disagreeing | Cover 80% | Dominant |")
    a("|---|--:|--:|--:|--:|:--:|")
    for g in groups:
        a("| %s | %d | %d | %d | %d | %s |"
          % (g["label"], g["variant_count"], g["workbooks_affected"],
             g["disagreeing_variants"], g["variants_covering_80pct_views"],
             "yes" if g["dominant"] else "**no**"))
    a("")
    a("_Sorted on absence of a dominant variant first: a contested concept is "
      "a harder adjudication than a many-variant one with a clear winner._")
    a("")
    if build == "working":
        _variant_detail(a, groups)


def _variant_detail(a, groups):
    contested = [g for g in groups if not g["dominant"]]
    if not contested:
        return
    a("### Variant detail (contested groups)")
    a("")
    for g in contested:
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
    zero = r.get("zero_view_workbooks", 0)
    a("- %d of %d workbooks drew no views in the window (recoverable capacity)."
      % (zero, total))
    a("- %d workbook(s) carry 80%% of all views (%d total views)."
      % (r.get("workbooks_covering_80pct_views", 0), r.get("total_views", 0)))
    a("- %d upstream table(s) feed more than one published source "
      "(max %d sources on one table) — candidate consolidation."
      % (r.get("redundant_source_tables", 0), r.get("max_sources_per_table", 0)))
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
