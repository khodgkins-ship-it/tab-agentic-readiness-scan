"""Compare two Estate Scan runs of one account over time.

The versioned, checksum-pinned query set exists so a customer can ask "why did
this number move" and get an answer that separates an estate change from a
definition change (build brief section 8; multi-run comparison was deferred in
the prototype). This module compares two `findings.json` artifacts -- each
`scan` writes its own into its own out-dir -- and renders a defensible delta.

Offline and deterministic: it reads two dicts and returns a third. No store, no
network, no model call. It reads only the build-agnostic counts and scores, so
it works against either build variant (redaction touches formula text, owner
names, and executed values -- never the headline numbers compared here).
"""

from typing import List, Optional

# Meta carried into the delta so the report can state exactly which two runs
# were compared and whether they are like-for-like.
_META_KEYS = ("run_id", "site_name", "scan_started_at", "scan_completed_at",
              "query_set_version", "tool_version", "generated_at")

# (json key, human label). Explicit lists so a comparison never silently starts
# or stops tracking a headline number when the findings dict grows a field.
_DM_MEASURES = (("contested_group_count", "Contested metric concepts"),)
_SEC_MEASURES = (
    ("user_context_field_count", "Access rules in the view layer"),
    ("affected_workbook_count", "Workbooks affected"))
_RT_MEASURES = (
    ("workbooks_total", "Workbooks total"),
    ("zero_view_workbooks", "Zero-view workbooks"),
    ("total_views", "Total views"),
    ("workbooks_covering_80pct_views", "Workbooks covering 80% of views"),
    ("redundant_source_tables", "Redundant upstream source tables"),
    ("max_sources_per_table", "Max sources on one table"))


def compare_runs(baseline, current):
    # type: (dict, dict) -> dict
    """Return the delta between two full findings dicts. `baseline` is the
    earlier run, `current` the later one; a positive numeric delta means the
    number rose from baseline to current."""
    b_meta = baseline.get("meta", {})
    c_meta = current.get("meta", {})
    warnings = []  # type: List[str]

    same_site = b_meta.get("site_name") == c_meta.get("site_name")
    if not same_site:
        warnings.append(
            "site differs (%s -> %s): these may be different estates, so the "
            "delta is not a like-for-like comparison."
            % (b_meta.get("site_name"), c_meta.get("site_name")))

    same_qs = b_meta.get("query_set_version") == c_meta.get("query_set_version")
    if not same_qs:
        warnings.append(
            "query set changed (%s -> %s): a moved number may reflect a changed "
            "definition, not a changed estate."
            % (b_meta.get("query_set_version"), c_meta.get("query_set_version")))

    return {
        "baseline": {k: b_meta.get(k) for k in _META_KEYS},
        "current": {k: c_meta.get(k) for k in _META_KEYS},
        "comparable": same_site and same_qs,
        "warnings": warnings,
        "facets": _facet_deltas(baseline, current),
        "domains": _domain_deltas(baseline, current),
        "findings": _finding_deltas(baseline, current),
        "coverage": _coverage_deltas(baseline, current),
        "flags": _flag_deltas(baseline, current),
    }


def _num_delta(b, c):
    # type: (object, object) -> Optional[float]
    # Only subtract when BOTH sides are real numbers; a facet unscored in one
    # run has no defensible delta and reports None, not a misleading zero.
    # (bool is an int subclass -- exclude it so a flag/quality boolean never
    # reads as a numeric change.)
    if (isinstance(b, (int, float)) and not isinstance(b, bool)
            and isinstance(c, (int, float)) and not isinstance(c, bool)):
        return c - b
    return None


def _facet_deltas(baseline, current):
    # type: (dict, dict) -> List[dict]
    b = {f["id"]: f for f in baseline.get("facets", [])}
    c = {f["id"]: f for f in current.get("facets", [])}
    out = []  # type: List[dict]
    for fid in sorted(set(b) | set(c)):
        bs = b.get(fid, {}).get("score")
        cs = c.get(fid, {}).get("score")
        out.append({"id": fid, "baseline": bs, "current": cs,
                    "delta": _num_delta(bs, cs)})
    return out


def _domain_deltas(baseline, current):
    # type: (dict, dict) -> List[dict]
    b = {d["id"]: d for d in baseline.get("domains", [])}
    c = {d["id"]: d for d in current.get("domains", [])}
    out = []  # type: List[dict]
    for did in sorted(set(b) | set(c)):
        bd, cd = b.get(did, {}), c.get(did, {})
        bb = bd.get("binding_constraints", []) or []
        cb = cd.get("binding_constraints", []) or []
        out.append({
            "id": did,
            "target_stage": {"baseline": bd.get("target_stage"),
                             "current": cd.get("target_stage")},
            "readiness": {"baseline": bd.get("readiness"),
                          "current": cd.get("readiness"),
                          "delta": _num_delta(bd.get("readiness"),
                                              cd.get("readiness"))},
            "gap": {"baseline": bd.get("gap"), "current": cd.get("gap"),
                    "delta": _num_delta(bd.get("gap"), cd.get("gap"))},
            "binding_constraints": {
                "baseline": bb, "current": cb,
                "added": [x for x in cb if x not in bb],
                "removed": [x for x in bb if x not in cb]},
        })
    return out


def _measure_block(b_find, c_find, specs):
    # type: (dict, dict, tuple) -> List[dict]
    out = []  # type: List[dict]
    for key, label in specs:
        bv, cv = b_find.get(key), c_find.get(key)
        out.append({"key": key, "label": label, "baseline": bv, "current": cv,
                    "delta": _num_delta(bv, cv)})
    return out


def _finding_deltas(baseline, current):
    # type: (dict, dict) -> dict
    bf = baseline.get("findings", {})
    cf = current.get("findings", {})
    return {
        "definition_multiplicity": _measure_block(
            bf.get("definition_multiplicity", {}),
            cf.get("definition_multiplicity", {}), _DM_MEASURES),
        "security_exposure": _measure_block(
            bf.get("security_exposure", {}),
            cf.get("security_exposure", {}), _SEC_MEASURES),
        "retirement": _measure_block(
            bf.get("retirement", {}), cf.get("retirement", {}), _RT_MEASURES),
    }


def _coverage_deltas(baseline, current):
    # type: (dict, dict) -> List[dict]
    b = {c["measure"]: c.get("status") for c in baseline.get("coverage", [])}
    c = {c["measure"]: c.get("status") for c in current.get("coverage", [])}
    out = []  # type: List[dict]
    for m in sorted(set(b) | set(c)):
        bs, cs = b.get(m), c.get(m)
        out.append({"measure": m, "baseline_status": bs, "current_status": cs,
                    "changed": bs != cs})
    return out


def _flag_deltas(baseline, current):
    # type: (dict, dict) -> dict
    b = {f["id"]: f for f in baseline.get("flags", [])}
    c = {f["id"]: f for f in current.get("flags", [])}
    count_changed = []  # type: List[dict]
    for fid in sorted(set(b) & set(c)):
        bc, cc = b[fid].get("count"), c[fid].get("count")
        if bc != cc:
            count_changed.append({"id": fid, "baseline": bc, "current": cc,
                                  "delta": _num_delta(bc, cc)})
    return {"appeared": sorted(set(c) - set(b)),
            "disappeared": sorted(set(b) - set(c)),
            "count_changed": count_changed}


# -- rendering ---------------------------------------------------------------

def _fmt(v):
    # type: (object) -> str
    return "—" if v is None else str(v)


def _fmt_delta(v):
    # type: (object) -> str
    if v is None:
        return "—"
    if v == 0:
        return "0"
    return ("+%s" if v > 0 else "%s") % v


def render_comparison_markdown(delta):
    # type: (dict) -> str
    lines = []  # type: List[str]
    a = lines.append
    b, c = delta["baseline"], delta["current"]

    a("# Tableau Estate Scan — run comparison")
    a("")
    a("- Baseline: run `%s` (%s), scanned %s — query set %s"
      % (_fmt(b.get("run_id")), b.get("site_name") or "unknown",
         _fmt(b.get("scan_completed_at")), _fmt(b.get("query_set_version"))))
    a("- Current: run `%s` (%s), scanned %s — query set %s"
      % (_fmt(c.get("run_id")), c.get("site_name") or "unknown",
         _fmt(c.get("scan_completed_at")), _fmt(c.get("query_set_version"))))
    a("")
    if delta.get("warnings"):
        a("> **Read with care — this is not a clean like-for-like delta.**")
        for w in delta["warnings"]:
            a("> - %s" % w)
        a("")
    elif delta.get("comparable"):
        a("_Same site and same query set: differences below are estate change, "
          "not definition change._")
        a("")

    _render_findings(a, delta.get("findings", {}))
    _render_facets(a, delta.get("facets", []))
    _render_domains(a, delta.get("domains", []))
    _render_flags(a, delta.get("flags", {}))
    _render_coverage(a, delta.get("coverage", []))

    a("")
    a("---")
    a("_No composite score is compared. Each number is shown on its own so a "
      "movement can be traced to its cause._")
    a("")
    return "\n".join(lines)


def _render_measure_rows(a, rows):
    # type: (object, List[dict]) -> None
    for r in rows:
        a("| %s | %s | %s | %s |"
          % (r["label"], _fmt(r["baseline"]), _fmt(r["current"]),
             _fmt_delta(r["delta"])))


def _render_findings(a, findings):
    # type: (object, dict) -> None
    a("## Findings")
    a("")
    a("| Measure | Baseline | Current | Change |")
    a("|---|--:|--:|--:|")
    _render_measure_rows(a, findings.get("definition_multiplicity", []))
    _render_measure_rows(a, findings.get("security_exposure", []))
    _render_measure_rows(a, findings.get("retirement", []))
    a("")


def _render_facets(a, facets):
    # type: (object, List[dict]) -> None
    changed = [f for f in facets if f["delta"] not in (None, 0)]
    a("## Facet scores")
    a("")
    if not changed:
        a("_No facet score changed._")
        a("")
        return
    a("| Facet | Baseline | Current | Change |")
    a("|---|--:|--:|--:|")
    for f in changed:
        a("| %s | %s | %s | %s |"
          % (f["id"], _fmt(f["baseline"]), _fmt(f["current"]),
             _fmt_delta(f["delta"])))
    a("")


def _render_domains(a, domains):
    # type: (object, List[dict]) -> None
    if not domains:
        return
    a("## Readiness by domain")
    a("")
    a("| Domain | Target | Readiness (base→cur) | Change | Binding change |")
    a("|---|--:|--:|--:|---|")
    for d in domains:
        rd = d["readiness"]
        bc = d["binding_constraints"]
        moves = []
        if bc["added"]:
            moves.append("+" + ", ".join(bc["added"]))
        if bc["removed"]:
            moves.append("-" + ", ".join(bc["removed"]))
        a("| %s | %s | %s→%s | %s | %s |"
          % (d["id"], _fmt(d["target_stage"]["current"]),
             _fmt(rd["baseline"]), _fmt(rd["current"]), _fmt_delta(rd["delta"]),
             "; ".join(moves) or "—"))
    a("")


def _render_flags(a, flags):
    # type: (object, dict) -> None
    appeared = flags.get("appeared", [])
    disappeared = flags.get("disappeared", [])
    changed = flags.get("count_changed", [])
    if not (appeared or disappeared or changed):
        return
    a("## Flags")
    a("")
    if appeared:
        a("- Newly firing: %s" % ", ".join(appeared))
    if disappeared:
        a("- No longer firing: %s" % ", ".join(disappeared))
    for ch in changed:
        a("- %s count %s → %s (%s)"
          % (ch["id"], _fmt(ch["baseline"]), _fmt(ch["current"]),
             _fmt_delta(ch["delta"])))
    a("")


def _render_coverage(a, coverage):
    # type: (object, List[dict]) -> None
    changed = [c for c in coverage if c["changed"]]
    if not changed:
        return
    a("## Coverage changes")
    a("")
    a("| Measure | Baseline | Current |")
    a("|---|---|---|")
    for c in changed:
        a("| %s | %s | %s |"
          % (c["measure"], _fmt(c["baseline_status"]),
             _fmt(c["current_status"])))
    a("")
