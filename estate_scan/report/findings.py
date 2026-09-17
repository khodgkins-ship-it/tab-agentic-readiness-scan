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
from estate_scan.flags import load_rules

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
            "governance_posture": _governance_posture(store, run_id),
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

# Sort order over the per-group `dominance` state: the hardest adjudication
# leads. A genuinely contested concept (>=2 definitions, none winning) is a
# governance problem and comes first; an unmeasured one (>=2 definitions, but
# usage was not measured so which wins is undeterminable) next; a settled one (a
# dominant definition) after; a singular concept (one definition -- not a
# multiplicity finding at all) last.
_DOMINANCE_ORDER = {"contested": 0, "unmeasured": 1, "dominant": 2, "singular": 3}


def _definition_multiplicity(store, run_id):
    # type: (object, str) -> dict
    # Dominance is usage-derived (rank.py aggregates views by definition), so it
    # is only determinable when usage_events measured. If that measure is not
    # `ok` (e.g. REST 501 on the live path), "no dominant definition" cannot be
    # asserted -- a concept is not "contested", its dominance is simply unknown
    # (plan invariant 7). Multiplicity itself -- whether a concept carries more
    # than one definition -- is structural and stays determinable regardless.
    #
    # A "definition" is a formula signature (definition_key), NOT a field: a
    # concept like "revenue" is one row even when forty fields compute it, and it
    # is "defined N ways" where N is the count of distinct definition_keys. The
    # field count is kept as variant_count for the working detail, but every
    # multiplicity / dominance decision is made over definitions.
    usage_measured = store.coverage_status(run_id, "usage_events") == "ok"
    groups = []  # type: List[dict]
    for g in store.metric_groups(run_id):
        gid = g["group_id"]
        variants = store.group_variant_detail(run_id, gid)
        group_views = sum((v["view_count"] or 0) for v in variants)
        variant_count = len(variants)
        definition_count = len({v["definition_key"] for v in variants})
        # "materially disagreeing" = distinct definitions among the variants that
        # carry usage; a definition nobody uses is not a live disagreement. Falls
        # back to all definitions when none carry usage.
        used_defs = {v["definition_key"] for v in variants
                     if (v["view_count"] or 0) > 0}
        disagreeing = len(used_defs) or definition_count
        has_dominant = any(v["is_dominant"] for v in variants)
        # A concept with a single definition is not multiplicity: there is
        # nothing to adjudicate and no dominance to determine. Only concepts with
        # >=2 definitions can be contested (and only when usage measured).
        multiplicity = definition_count >= 2
        if not multiplicity:
            dominance = "singular"
        elif not usage_measured:
            dominance = "unmeasured"
        elif has_dominant:
            dominance = "dominant"
        else:
            dominance = "contested"
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
            "variant_count": variant_count,
            "definition_count": definition_count,
            "workbooks_affected": store.group_workbook_count(run_id, gid),
            "disagreeing_variants": disagreeing,
            "variants_covering_80pct_views": cover80_for(store, run_id, gid),
            "group_views": group_views,
            "multiplicity": multiplicity,
            "dominance": dominance,
            # Kept for the working-detail artifacts (variants.xlsx) and the
            # comparison: True only when a variant actually wins. A singular or
            # unmeasured concept is False here, but the `dominance` state above is
            # what the report renders so "no" is never shown for those.
            "dominant": dominance == "dominant",
            "variants": [_variant(v, group_views, exec_by_field.get(v["field_id"]))
                         for v in variants],
        }
        if exec_rows:
            group["execution"] = _execution_summary(exec_rows)
        groups.append(group)
    groups.sort(key=lambda x: (_DOMINANCE_ORDER[x["dominance"]],
                               -x["disagreeing_variants"],
                               -x["definition_count"],
                               -x["variant_count"], x["label"]))
    multiplicity_groups = [g for g in groups if g["multiplicity"]]
    return {
        "groups": groups,
        "usage_measured": usage_measured,
        # Concepts carrying more than one definition -- the real multiplicity
        # count, determinable with or without usage.
        "multiplicity_group_count": len(multiplicity_groups),
        # Of those, the ones with no dominant variant. Zero when usage was not
        # measured: a contest we cannot see is not asserted.
        "contested_group_count": sum(
            1 for g in multiplicity_groups if g["dominance"] == "contested"),
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
    # The source-fanout consolidation signal is from lineage and always real.
    # The view-based retirement signal depends on usage_events: if that measure
    # is not `ok` (e.g. it returned 501 on the live path), zero views means
    # "not measured", NOT "recoverable capacity". Null those fields rather than
    # emit 0, so nothing reads as "every workbook is dead" (plan invariant 7).
    total = store.workbook_count(run_id)
    fanout = store.upstream_table_fanout(run_id)
    redundant = [r for r in fanout if (r["sources"] or 0) > 1]
    usage_measured = store.coverage_status(run_id, "usage_events") == "ok"
    out = {
        "workbooks_total": total,
        "usage_measured": usage_measured,
        "redundant_source_tables": len(redundant),
        "max_sources_per_table": max((r["sources"] for r in fanout), default=0),
    }
    if usage_measured:
        zero = store.zero_view_workbooks(run_id)
        views = sorted(store.workbook_view_counts(run_id), reverse=True)
        out.update({
            "zero_view_workbooks": len(zero),
            "total_views": sum(views),
            "workbooks_covering_70pct_views": _cover_count(views, 0.7),
            "workbooks_covering_80pct_views": _cover_count(views, 0.8),
            "unused_workbook_sample": [
                {"name": w["name"], "project_name": w["project_name"]}
                for w in zero[:25]],
        })
    else:
        out.update({
            "zero_view_workbooks": None,
            "total_views": None,
            "workbooks_covering_70pct_views": None,
            "workbooks_covering_80pct_views": None,
            "unused_workbook_sample": [],
        })
    return out


# -- finding four: governance posture (observed presence evidence) -----------

def _governance_posture(store, run_id):
    # type: (object, str) -> dict
    """Non-gating observed-presence evidence for a governance arc the scan can
    witness the *mechanism* of but does not *score* (build plan R4, the third
    signal category). The scored arcs -- accountability (ownership coverage) and
    assurance (certification coverage) -- already feed the maturity loop; this
    block is different: it proves a governance mechanism EXISTS and is exercised
    at all, and hands the interview concrete good and bad examples to dig into.
    It adjusts NO maturity gate -- the detective arc stays interview-scored --
    so it lives in `findings`, not in the facet/domain register.

    Coverage is first-class throughout: an unmeasured feed reads `unmeasured`,
    never `not_exercised`. Absence of measurement is not absence of the
    mechanism, and the interview must be told which it is looking at."""
    return {
        "note": (
            "Observed presence of governance mechanisms. Proof the mechanism is "
            "in place and exercised, with good and bad examples for the "
            "interview to probe -- observed by the scan, assessed by the "
            "interview. Adjusts no maturity gate."),
        # Ordered as the governance loop activates the arcs (rules.yaml
        # governance_arcs): preventive first, then detective.
        "arcs": [_preventive_posture(store, run_id),
                 _detective_posture(store, run_id)],
    }


def _detective_posture(store, run_id):
    # type: (object, str) -> dict
    """The detective arc: does the estate run mechanisms that would *catch* a
    data problem (certification attestations, data-quality warnings), and do the
    two signals agree? Presence + divergence only; the tier is the interview's
    to set."""
    ds_ok = store.coverage_status(run_id, "datasources") == "ok"
    dqw_ok = store.coverage_status(run_id, "data_quality_warnings") == "ok"

    certified, published = store.datasource_certification_counts(run_id)
    certification = _mechanism_presence(
        "certification", ds_ok, exercised=(ds_ok and certified > 0),
        detail={"certified_sources": certified if ds_ok else None,
                "published_sources": published if ds_ok else None})

    active, dqw_total = store.data_quality_warning_counts(run_id)
    dqw = _mechanism_presence(
        "data_quality_warnings", dqw_ok, exercised=(dqw_ok and dqw_total > 0),
        detail={"warnings_total": dqw_total if dqw_ok else None,
                "warnings_active": active if dqw_ok else None})

    return {
        "arc": "detective",
        # The observed presence does not score the arc; the specialist does,
        # informed by this evidence. Named explicitly so the report cannot imply
        # a scan-derived tier.
        "scored_by": "interview",
        "mechanisms": [certification, dqw],
        "divergence": _detective_divergence(store, run_id, ds_ok and dqw_ok),
    }


def _mechanism_presence(mechanism, measured, exercised, detail):
    # type: (str, bool, bool, dict) -> dict
    """One governance mechanism's presence signal. `unmeasured` when the feed
    was not measured (coverage first-class -- NOT `not_exercised`); otherwise
    `in_use` when it is exercised, `not_exercised` when the feed is measured but
    the mechanism is going unused (a real, provable finding)."""
    if not measured:
        status = "unmeasured"
    elif exercised:
        status = "in_use"
    else:
        status = "not_exercised"
    out = {"mechanism": mechanism, "measured": measured, "status": status}
    out.update(detail)
    return out


def _detective_divergence(store, run_id, measured):
    # type: (object, str, bool) -> dict
    """Certified sources that nonetheless carry an ACTIVE data-quality warning
    (the GOV-03 divergence set) as the "bad examples", and certified sources
    that are clean as the "good examples" -- the interview shows the specialist
    what good and bad look like on this estate. Needs both the datasources and
    data-quality-warning feeds measured; unmeasured is reported honestly rather
    than as zero divergence. Source names only, no owner names."""
    if not measured:
        return {"measured": False, "count": None,
                "bad_examples": [], "good_examples": []}
    seen = set()  # type: set
    bad = []  # type: List[dict]
    for r in store.certified_sources_with_active_warning(run_id):
        # A source can carry more than one active warning; count it once.
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        bad.append({"datasource_name": r["name"] or r["id"],
                    "warning_type": r["warning_type"],
                    "is_elevated": bool(r["is_elevated"])})
    good = [{"datasource_name": r["name"] or r["id"]}
            for r in store.certified_sources_without_active_warning(run_id, 10)]
    return {
        "measured": True,
        "count": len(bad),
        "bad_examples": bad[:10],
        "good_examples": good,
    }


def _preventive_posture(store, run_id):
    # type: (object, str) -> dict
    """The preventive arc: does the estate exercise access control at all
    (explicit permission grants), and does it use explicit restriction (Deny
    rules)? Plus the exposure evidence -- broad grants of a powerful capability
    -- and scoped counter-examples. Presence + exposure only; the tier is the
    interview's to set. SEC-02 the flag scores permissive-grant *firing*
    separately; this block never gates."""
    perms_ok = store.coverage_status(run_id, "permissions") == "ok"
    total, objects, deny = (store.permission_grant_counts(run_id)
                            if perms_ok else (0, 0, 0))

    scoping = _mechanism_presence(
        "permission_grants", perms_ok, exercised=(perms_ok and total > 0),
        detail={"grants_total": total if perms_ok else None,
                "objects_covered": objects if perms_ok else None})
    restriction = _mechanism_presence(
        "explicit_deny", perms_ok, exercised=(perms_ok and deny > 0),
        detail={"deny_rules": deny if perms_ok else None})

    return {
        "arc": "preventive",
        # As with the detective arc, the observed presence does not score the
        # tier; the specialist does, informed by this evidence.
        "scored_by": "interview",
        "mechanisms": [scoping, restriction],
        "exposure": _preventive_exposure(store, run_id, perms_ok),
    }


def _permissive_policy():
    # type: () -> tuple
    """Which grantees count as an 'everyone' group and which capabilities count
    as sensitive -- sourced from the SEC-02 rule so the exposure evidence uses
    the SAME definition as the flag and can never contradict it. Defaults mirror
    the SEC-02 evaluator (flags/engine.py) so a missing entry degrades to the
    shipped policy rather than silently widening exposure."""
    th = (load_rules().get("flags", {}).get("SEC-02", {}) or {}).get(
        "threshold", {}) or {}
    everyone = set(th.get("everyone_grantees", ["AllUsers"]))
    sensitive = set(th.get("sensitive_capabilities",
                           ["Write", "Delete", "ChangePermissions",
                            "ProjectLeader"]))
    return everyone, sensitive


def _preventive_exposure(store, run_id, measured):
    # type: (object, str, bool) -> dict
    """Permissive grants -- an Allow of a sensitive capability to an 'everyone'
    group -- as the "bad examples" (the SEC-02 exposure set), and the same
    sensitive capabilities scoped to a NAMED group as the "good examples". Needs
    the permissions feed measured; unmeasured is reported honestly, never as
    zero exposure. Object/group identifiers only -- good examples are restricted
    to group grantees by construction, so a user name can never leak."""
    if not measured:
        return {"measured": False, "count": None,
                "bad_examples": [], "good_examples": []}
    everyone, sensitive = _permissive_policy()
    bad = []   # type: List[dict]
    good = []  # type: List[dict]
    for r in store.permission_grants(run_id):
        if r["mode"] != "Allow" or r["capability"] not in sensitive:
            continue
        row = {"object_type": r["object_type"], "object_id": r["object_id"],
               "capability": r["capability"], "grantee": r["grantee_id"]}
        if r["grantee_id"] in everyone:
            bad.append(row)
        elif r["grantee_type"] == "group":
            good.append(row)
    return {
        "measured": True,
        "count": len(bad),
        "bad_examples": bad[:10],
        "good_examples": good[:10],
    }


def _flag_by_id(flags, flag_id):
    # type: (List[dict], str) -> Optional[dict]
    for f in flags:
        if f["id"] == flag_id:
            return f
    return None
