"""Assemble the full findings dict -- the contract every artifact renders from.

This is a superset of the scoring contract (build spec 9.6): it wraps the
scorer's `facets` and `domains` with the flag list, the coverage register, run
metadata, and the three GTM findings (definition multiplicity, security
exposure, retirement) derived from the store. One source of truth, several
consumers.

It never carries a top-level `score` field -- there is no composite anywhere,
by design (build spec 9.5), and `test_report.py` asserts it.
"""

import datetime
import json
import re
from typing import Dict, List, Optional

from estate_scan import (APP_TEMPLATE_VERSION, QUERY_SET_VERSION, TOOL_VERSION)
from estate_scan.derive.group import USER_CONTEXT_FUNCS
from estate_scan.derive.rank import _cover_count, cover80_for

_UC_RE = re.compile(r"\b(" + "|".join(USER_CONTEXT_FUNCS) + r")\s*\(",
                    re.IGNORECASE)


def build_findings(store, run_id, now=None):
    # type: (object, str, Optional[str]) -> dict
    """Assemble findings for `run_id`. Requires that `score` has already run --
    the per-domain register is read from the persisted score output rather than
    recomputed, so report and score can never disagree."""
    now = now or (datetime.datetime.utcnow().isoformat() + "Z")
    facets, domains = _score(store, run_id)
    flags = _flags(store, run_id)
    return {
        "meta": _meta(store, run_id, now),
        "facets": facets,
        "domains": domains,
        "flags": flags,
        "coverage": _coverage(store, run_id),
        "findings": {
            "definition_multiplicity": _definition_multiplicity(store, run_id),
            "security_exposure": _security_exposure(store, run_id, flags),
            "retirement": _retirement(store, run_id),
        },
    }


# -- scoring register (from the persisted score output) ----------------------

def _score(store, run_id):
    # type: (object, str) -> tuple
    row = store.score_output(run_id)
    if row is None:
        raise ValueError(
            "no score output for run %s; run `score` before `report`" % run_id)
    parsed = json.loads(row["findings_json"])
    return parsed.get("facets", []), parsed.get("domains", [])


def _flags(store, run_id):
    # type: (object, str) -> List[dict]
    out = []  # type: List[dict]
    for r in store.flags(run_id):
        out.append({
            "id": r["flag_id"], "severity": r["severity"],
            "confidence": r["confidence"], "facet": r["facet"],
            "domain": r["domain"], "count": r["count"],
            "evidence": json.loads(r["evidence_json"] or "{}")})
    return out


def _coverage(store, run_id):
    # type: (object, str) -> List[dict]
    return [{"measure": r["measure"], "status": r["status"],
             "reason": r["reason"]} for r in store.coverage(run_id)]


def _meta(store, run_id, now):
    # type: (object, str, str) -> dict
    row = store.run_meta(run_id)
    config = store.run_config(run_id) or {}
    site = config.get("site") or {}
    return {
        "run_id": run_id,
        "generated_at": now,
        "tool_version": (row["tool_version"] if row else None) or TOOL_VERSION,
        "query_set_version": (
            (row["query_set_version"] if row else None) or QUERY_SET_VERSION),
        "app_template_version": APP_TEMPLATE_VERSION,
        "grouping_mode": (
            "model_assisted" if (row and row["model_pass"]) else "local"),
        "deployment_type": row["deployment_type"] if row else None,
        "adoption_source": row["adoption_source"] if row else None,
        "site_name": (row["site_name"] if row else None) or site.get("name"),
        "scan_started_at": row["started_at"] if row else None,
        "scan_completed_at": row["completed_at"] if row else None,
        "profile": config.get("profile"),
        "core_metrics": config.get("core_metrics", []),
    }


# -- finding one: definition multiplicity ------------------------------------

def _definition_multiplicity(store, run_id):
    # type: (object, str) -> dict
    groups = []  # type: List[dict]
    for g in store.metric_groups(run_id):
        gid = g["group_id"]
        variants = store.group_variant_detail(run_id, gid)
        group_views = sum((v["view_count"] or 0) for v in variants)
        # "materially disagreeing" = distinct resolved definitions among the
        # variants that carry usage; a definition nobody uses is not a live
        # disagreement. Falls back to all variants when none carry usage.
        used_hashes = {v["normalized_hash"] for v in variants
                       if (v["view_count"] or 0) > 0}
        disagreeing = len(used_hashes) or len(
            {v["normalized_hash"] for v in variants})
        dominant = any(v["is_dominant"] for v in variants)
        # Optional VDS join (R3): when the full-mode `resolve` step executed this
        # group, attach each variant's tested figure and the group's reference +
        # most-material pair. Absent (empty map) when VDS did not run, so the
        # rendered shape is exactly as before -- backward compatible.
        exec_rows = store.variant_execution_detail(run_id, gid)
        exec_by_field = {r["field_id"]: r for r in exec_rows}
        group = {
            "group_id": gid,
            "label": g["canonical_label"],
            "method": g["method"],
            "confidence": g["confidence"],
            "variant_count": len(variants),
            "workbooks_affected": store.group_workbook_count(run_id, gid),
            "disagreeing_variants": disagreeing,
            "variants_covering_80pct_views": cover80_for(store, run_id, gid),
            "group_views": group_views,
            "dominant": dominant,
            "variants": [_variant(v, group_views, exec_by_field.get(v["field_id"]))
                         for v in variants],
        }
        if exec_rows:
            group["execution"] = _execution_summary(exec_rows)
        groups.append(group)
    # Sort on absence of a dominant variant first, not variant count: fewer
    # variants with no clear candidate is the harder adjudication (build brief
    # section 6). Ties broken by disagreement, then size, then label.
    groups.sort(key=lambda x: (x["dominant"], -x["disagreeing_variants"],
                               -x["variant_count"], x["label"]))
    return {
        "groups": groups,
        "contested_group_count": sum(1 for g in groups if not g["dominant"]),
    }


def _variant(v, group_views, ex=None):
    # type: (object, int, Optional[object]) -> dict
    views = v["view_count"] or 0
    out = {
        "field_name": v["field_name"],
        "usage_rank": v["usage_rank"],
        "view_count": views,
        "workbook_count": v["workbook_count"] or 0,
        "view_share": round(views / float(group_views), 4) if group_views else 0.0,
        "is_dominant": bool(v["is_dominant"]),
        "resolution_status": v["resolution_status"],
        # Redacted out of the presentation build (report/redact.py).
        "resolved_formula": v["resolved_formula"],
        "owner": v["owner"],
        "datasource_name": v["datasource_name"],
    }
    if ex is not None:
        out["execution"] = _variant_execution(ex)
    return out


def _variant_execution(ex):
    # type: (object) -> dict
    """Per-variant VDS result. `value` is the raw returned aggregate -- redacted
    from the presentation build (report/redact.py); the diff figures are safe in
    both builds. An unexecuted variant carries its class + reason and a null
    value, so it never reads as agreeing."""
    return {
        "executability_class": ex["executability_class"],
        "untested_reason": ex["untested_reason"],
        "is_reference": bool(ex["is_reference"]),
        "period": ex["period"],
        "context_applied": bool(ex["context_applied"]),
        "value": ex["value"],
        "abs_diff": ex["abs_diff"],
        "rel_diff": ex["rel_diff"],
        "material": (bool(ex["material"]) if ex["material"] is not None else None),
    }


def _execution_summary(exec_rows):
    # type: (List[object]) -> dict
    """Group-level VDS rollup: the reference variant, tested/untested counts, the
    executability distribution, and the single most-material pair (reference vs
    the variant with the largest relative gap). `reference_value`/`variant_value`
    are raw figures -- redacted from the presentation build."""
    by_class = {}  # type: dict
    tested = 0
    reference_field = None
    reference_value = None
    most = None
    for r in exec_rows:
        cls = r["executability_class"]
        by_class[cls] = by_class.get(cls, 0) + 1
        if cls == "executable":
            tested += 1
        if r["is_reference"]:
            reference_field = r["field_name"]
            reference_value = r["value"]
        if r["rel_diff"] is not None and not r["is_reference"]:
            if most is None or r["rel_diff"] > most["rel_diff"]:
                most = {
                    "field_name": r["field_name"],
                    "value": r["value"],
                    "abs_diff": r["abs_diff"],
                    "rel_diff": r["rel_diff"],
                    "material": (bool(r["material"])
                                 if r["material"] is not None else None),
                }
    material = any(bool(r["material"]) for r in exec_rows
                   if r["material"] is not None and not r["is_reference"])
    pair = None
    if most is not None:
        pair = {
            "reference_field": reference_field,
            "reference_value": reference_value,
            "variant_field": most["field_name"],
            "variant_value": most["value"],
            "abs_diff": most["abs_diff"],
            "rel_diff": most["rel_diff"],
            "material": most["material"],
        }
    return {
        "period": exec_rows[0]["period"],
        "reference_field": reference_field,
        "tested": tested,
        "untested": len(exec_rows) - tested,
        "executability": by_class,
        "material_disagreement": material,
        "most_material_pair": pair,
    }


# -- finding two: security exposure ------------------------------------------

def _security_exposure(store, run_id, flags):
    # type: (object, str, List[dict]) -> dict
    uc_fields = [f for f in store.calc_field_detail(run_id)
                 if _UC_RE.search(f["formula"] or "")]
    field_ids = [f["id"] for f in uc_fields]
    workbooks = store.workbooks_for_fields(run_id, field_ids)
    sec01 = _flag_by_id(flags, "SEC-01")
    return {
        "user_context_field_count": len(uc_fields),
        "affected_workbook_count": len(workbooks),
        "severity": sec01["severity"] if sec01 else None,
        "fields": [{"name": f["name"], "formula": f["formula"],
                    "datasource_name": f["datasource_name"],
                    "owner": f["owner"]} for f in uc_fields],
        "affected_workbooks": [{"name": w["name"], "owner": w["owner"]}
                               for w in workbooks],
    }


# -- finding three: retirement case ------------------------------------------

def _retirement(store, run_id):
    # type: (object, str) -> dict
    total = store.workbook_count(run_id)
    zero = store.zero_view_workbooks(run_id)
    views = sorted(store.workbook_view_counts(run_id), reverse=True)
    fanout = store.upstream_table_fanout(run_id)
    redundant = [r for r in fanout if (r["sources"] or 0) > 1]
    return {
        "workbooks_total": total,
        "zero_view_workbooks": len(zero),
        "total_views": sum(views),
        "workbooks_covering_70pct_views": _cover_count(views, 0.7),
        "workbooks_covering_80pct_views": _cover_count(views, 0.8),
        "redundant_source_tables": len(redundant),
        "max_sources_per_table": max((r["sources"] for r in fanout), default=0),
        "unused_workbook_sample": [
            {"name": w["name"], "project_name": w["project_name"]}
            for w in zero[:25]],
    }


def _flag_by_id(flags, flag_id):
    # type: (List[dict], str) -> Optional[dict]
    for f in flags:
        if f["id"] == flag_id:
            return f
    return None
