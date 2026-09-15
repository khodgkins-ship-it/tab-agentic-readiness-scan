"""Render the single-file report web app.

The three source files under `report/webapp/` (app.html, app.css, app.js) are
kept separate for maintainability and concatenated here at emit time, so the
output is one self-contained `.html` with no adjacent assets and no network
calls (report web app spec section 7).

The embedded payload is a documented *subset* of `findings.json`, not a
parallel format: one source of truth, two consumers. `webapp_payload` selects
only the keys the app reads. If the payload ever approaches the size ceiling,
unscoped variant detail is dropped first (spec section 2); the hook for that is
`_trim_variants`.
"""

import json
import os
from typing import List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEBAPP_DIR = os.path.join(_HERE, "webapp")

# Presentation build embeds no formula text at all: the redactor has already
# replaced it with this marker, and the payload builder drops the security
# `fields` list (which carries formula text in the working build) entirely.
_REDACTED = "[redacted]"


def _read(name):
    # type: (str) -> str
    with open(os.path.join(_WEBAPP_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


def webapp_payload(findings):
    # type: (dict) -> dict
    """Project `findings` down to the documented subset the app renders."""
    meta = findings.get("meta", {})
    fnd = findings.get("findings", {})
    return {
        "meta": {k: meta.get(k) for k in (
            "run_id", "generated_at", "build", "framing", "site_name",
            "profile", "scan_started_at", "scan_completed_at", "grouping_mode",
            "adoption_source", "tool_version", "query_set_version",
            "app_template_version")},
        "facets": [_facet(f) for f in findings.get("facets", [])],
        "domains": [_domain(d) for d in findings.get("domains", [])],
        "flags": [{k: fl.get(k) for k in
                   ("id", "severity", "confidence", "facet", "domain", "count")}
                  for fl in findings.get("flags", [])],
        "coverage": [{k: c.get(k) for k in ("measure", "status", "reason")}
                     for c in findings.get("coverage", [])],
        "findings": {
            "definition_multiplicity": _dm(fnd.get("definition_multiplicity", {})),
            "security_exposure": _security(fnd.get("security_exposure", {})),
            "retirement": _retirement(fnd.get("retirement", {})),
        },
    }


def _facet(f):
    # type: (dict) -> dict
    return {k: f.get(k) for k in
            ("id", "dimension", "score", "evidence", "confidence", "gates")}


def _domain(d):
    # type: (dict) -> dict
    return {k: d.get(k) for k in
            ("id", "target_stage", "readiness", "gap", "binding_constraints",
             "unscored_dimensions", "confidence")}


def _dm(dm):
    # type: (dict) -> dict
    return {
        "contested_group_count": dm.get("contested_group_count", 0),
        "groups": [_dm_group(g) for g in dm.get("groups", [])],
    }


def _dm_group(g):
    # type: (dict) -> dict
    out = {
        "group_id": g.get("group_id"),
        "label": g.get("label"),
        "variant_count": g.get("variant_count"),
        "workbooks_affected": g.get("workbooks_affected"),
        "disagreeing_variants": g.get("disagreeing_variants"),
        "variants_covering_80pct_views": g.get("variants_covering_80pct_views"),
        "dominant": g.get("dominant"),
        "variants": [_variant(v) for v in g.get("variants", [])],
    }
    # R5: carry the group-level VDS rollup so the app can render the same-period
    # side-by-side (the single most persuasive element, spec 04 section 4.2).
    # Absent unless the full-mode `resolve` step ran, so the shape is unchanged
    # for a scan-only run. Raw values were already redacted by report/redact.py
    # before this projection, so the presentation payload carries only diffs.
    if g.get("execution") is not None:
        out["execution"] = _group_exec(g["execution"])
    return out


def _group_exec(gx):
    # type: (dict) -> dict
    pair = gx.get("most_material_pair")
    return {
        "period": gx.get("period"),
        "reference_field": gx.get("reference_field"),
        "tested": gx.get("tested"),
        "untested": gx.get("untested"),
        "executability": gx.get("executability"),
        "material_disagreement": gx.get("material_disagreement"),
        "most_material_pair": ({k: pair.get(k) for k in (
            "reference_field", "reference_value", "variant_field",
            "variant_value", "abs_diff", "rel_diff", "material")}
            if pair else None),
    }


def _variant(v):
    # type: (dict) -> dict
    out = {k: v.get(k) for k in (
        "field_name", "usage_rank", "view_count", "workbook_count",
        "view_share", "is_dominant", "resolution_status", "resolved_formula",
        "owner", "datasource_name")}
    # R5: per-variant VDS figure. `value` is already redacted to "[redacted]" in
    # the presentation build; the executability class, reason, and diffs stay.
    ex = v.get("execution")
    if ex is not None:
        out["execution"] = {k: ex.get(k) for k in (
            "executability_class", "untested_reason", "is_reference", "period",
            "context_applied", "value", "abs_diff", "rel_diff", "material")}
    return out


def _security(s):
    # type: (dict) -> dict
    # Drop `fields` (it carries formula text in the working build); the app
    # renders only the affected-workbook list, so the formulas never reach the
    # embedded payload.
    return {
        "user_context_field_count": s.get("user_context_field_count", 0),
        "affected_workbook_count": s.get("affected_workbook_count", 0),
        "severity": s.get("severity"),
        "affected_workbooks": [{"name": w.get("name"), "owner": w.get("owner")}
                               for w in s.get("affected_workbooks", [])],
    }


def _retirement(r):
    # type: (dict) -> dict
    return {k: r.get(k) for k in (
        "workbooks_total", "zero_view_workbooks", "total_views",
        "workbooks_covering_70pct_views", "workbooks_covering_80pct_views",
        "redundant_source_tables", "max_sources_per_table")}


def _trim_variants(payload):
    # type: (dict) -> dict
    """Size-ceiling escape hatch: strip variant detail from groups that have a
    dominant variant, keeping the contested groups intact. Not wired in by
    default -- the prototype fixtures stay well under 5 MB -- but this is where
    the drop happens if a large estate pushes the payload over."""
    dm = payload.get("findings", {}).get("definition_multiplicity", {})
    for g in dm.get("groups", []):
        if g.get("dominant"):
            g["variants"] = []
    return payload


def _embed_json(payload):
    # type: (dict) -> str
    # Escape "<" so a "</script>" inside any string cannot close the host
    # script element; harmless everywhere else.
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def render_html(findings):
    # type: (dict) -> str
    """Concatenate the template, styles, script, and embedded payload into one
    self-contained HTML document."""
    payload = webapp_payload(findings)
    html = _read("app.html")
    html = html.replace("/*__CSS__*/", _read("app.css"))
    # Replace the JS marker before the payload so a "/*__JS__*/" that somehow
    # appears in data cannot collide with the script slot.
    html = html.replace("/*__JS__*/", _read("app.js"))
    html = html.replace("__PAYLOAD__", _embed_json(payload))
    return html
