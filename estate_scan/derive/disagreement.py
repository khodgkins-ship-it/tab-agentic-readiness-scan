"""Material-disagreement resolution via VDS (R3).

SEM-02 in the scan is a *structural* proxy: distinct resolved definitions among
the used variants of a metric group. This module adds the *consequence* layer --
for a contested group it asks the site what each executable variant actually
returns for one agreed period, and records the gap between the group's reference
variant and the others. It never disturbs the structural finding; it attaches to
it (see `report/findings.py::_definition_multiplicity`).

Two gates, both honest:

  * the `vizql_data_service` capability must be present. Off -> coverage
    `material_disagreement` is recorded `skipped` with a reason, never silently
    clean, and no rows are written.
  * it runs only in a separate full-mode step with the analyst present and a
    fixed period + tolerance agreed *before* results are shown (02 §332-340). It
    is never part of the scan loop.

Every variant is first classified -- executable / context_bound / unresolvable /
not_comparable -- leaning on the resolver verdict already in
`resolved_formulas.resolution_status`. An unexecuted variant is stored with its
class and reason and a NULL value, so it is reported, never counted as agreeing.
Raw returned values are stored for the working build only; abs_diff/rel_diff/
material are the safe comparison figures carried in both builds.
"""

import datetime
import re
from typing import List, Optional, Tuple

from estate_scan.derive.group import USER_CONTEXT_FUNCS
from estate_scan.derive.resolve import RESOLVED

EXECUTABLE = "executable"
CONTEXT_BOUND = "context_bound"
UNRESOLVABLE = "unresolvable"
NOT_COMPARABLE = "not_comparable"

# Default budget cap for a resolve run: at most this many groups, or this many
# VDS queries, whichever binds first. A live estate can carry thousands of groups
# and thousands of executable variants; running them all would send one read per
# executable variant. The analyst almost always wants only the top of the
# adjudication backlog, so the cap defaults small and is overridable from the CLI.
DEFAULT_MAX_GROUPS = 10
DEFAULT_MAX_QUERIES = 1000

# Priority ordering for the budget cap. This is the same contested-first
# adjudication backlog the report surfaces (report/findings.py
# ::_definition_multiplicity): a genuinely contested concept (>=2 definitions,
# none dominant) leads, then unmeasured, then a settled dominant one, then a
# singular concept. So "the top N groups" here means exactly the groups a reader
# sees ranked first in the report.
_DOMINANCE_ORDER = {"contested": 0, "unmeasured": 1, "dominant": 2, "singular": 3}

_MEASURE_ROLE = "measure"
# Same user-context function list SEC-01/grouping use: a resolved formula that
# depends on the viewer (USERNAME(), ISMEMBEROF(), ...) yields a per-viewer value,
# so a single server-side aggregate would be misleading -- context_bound, not run.
_UC_RE = re.compile(r"\b(" + "|".join(USER_CONTEXT_FUNCS) + r")\s*\(",
                    re.IGNORECASE)

# Tableau aggregate functions. A resolved formula containing one of these already
# returns an aggregate, so VDS must be asked for the field's NATIVE aggregation
# (no wrapping function): wrapping it in an outer SUM is rejected (errorCode
# 400800 "already an aggregation, cannot be further aggregated"), and even a
# non-numeric field trips 400803 when a function is forced. On real estates this
# is the overwhelming case -- calculated metrics (COUNTD, ratios, FIXED LODs)
# rather than raw numeric columns. WINDOW_*/RUNNING_*/TOTAL are table calcs; they
# also return aggregated results, so they take the native path too.
_AGG_RE = re.compile(
    r"\b(SUM|AVG|COUNTD|COUNT|MIN|MAX|MEDIAN|ATTR|STDEV|STDEVP|VAR|VARP|"
    r"PERCENTILE|CORR|COVAR|COVARP|TOTAL|RUNNING_\w+|WINDOW_\w+)\s*\(",
    re.IGNORECASE)


def vds_function(resolved_formula, default="SUM"):
    # type: (Optional[str], Optional[str]) -> Optional[str]
    """The VDS aggregation to request for a variant. A resolved formula that
    already contains an aggregate function must be queried with its native
    aggregation (return None -> `build_query_body` omits the `function` key);
    only a genuinely raw numeric column gets `default`."""
    if _AGG_RE.search(resolved_formula or ""):
        return None
    return default


def classify_variant(row):
    # type: (object) -> Tuple[str, str]
    """Classify one variant for VDS execution, returning ``(class, reason)``.

    * `unresolvable` -- the formula did not resolve (unresolved reference, cycle,
      or too deep). Only a `resolved` formula is ever executed, so an unresolved
      one is reported unrunnable, never silently clean.
    * `context_bound` -- resolved, but depends on user context; a single
      aggregate is not comparable across viewers.
    * `not_comparable` -- resolved, but the owning source has no queryable LUID,
      or the field is not an aggregatable measure.
    * `executable` -- resolved, a measure, on a source with a LUID.
    """
    status = row["resolution_status"]
    if status != RESOLVED:
        return UNRESOLVABLE, "formula did not resolve (%s)" % (status or "no resolution")
    if _UC_RE.search(row["resolved_formula"] or ""):
        return CONTEXT_BOUND, "resolved formula depends on user context"
    if not (row["datasource_luid"] or "").strip():
        return NOT_COMPARABLE, "owning data source has no queryable LUID"
    if (row["role"] or "").strip().lower() != _MEASURE_ROLE:
        return NOT_COMPARABLE, ("field is not an aggregatable measure (role=%s)"
                                % (row["role"] or "?"))
    return EXECUTABLE, ""


def _pick_reference(classed, values=None):
    # type: (list, Optional[dict]) -> Optional[object]
    """The baseline variant to diff the others against: the dominant one if any,
    else the executable variant with the best (lowest) usage rank. Only an
    executable variant can be a reference -- a diff against an unrunnable baseline
    would be meaningless. Returns None when nothing is executable.

    When `values` (field_id -> executed figure) is supplied, prefer a reference
    that actually returned a value: a None baseline (its VDS query failed or came
    back empty) would collapse every diff in the group to NULL and report a false
    "no disagreement". Only if no executable variant returned a value do we fall
    back to the full executable pool, so a reference is still marked."""
    executable = [r for r, cls, _ in classed if cls == EXECUTABLE]
    if not executable:
        return None
    if values is not None:
        with_value = [r for r in executable
                      if values.get(r["field_id"]) is not None]
        if with_value:
            executable = with_value
    dominant = [r for r in executable if r["is_dominant"]]
    pool = dominant or executable
    return min(pool, key=lambda r: (r["usage_rank"]
                                    if r["usage_rank"] is not None else 1 << 30))


def _ordered_groups(store, run_id):
    # type: (object, str) -> list
    """Metric groups in the report's contested-first priority order, so the
    budget cap resolves the top of the adjudication backlog first. Mirrors the
    dominance classification and sort key in report/findings.py
    ::_definition_multiplicity (dominance state, then most-disagreeing, most
    definitions, most variants, then label) -- kept here rather than imported so
    `derive` never depends on `report`."""
    usage_measured = store.coverage_status(run_id, "usage_events") == "ok"
    ranked = []
    for g in store.metric_groups(run_id):
        detail = store.group_variant_detail(run_id, g["group_id"])
        definition_count = len({v["definition_key"] for v in detail})
        used_defs = {v["definition_key"] for v in detail
                     if (v["view_count"] or 0) > 0}
        disagreeing = len(used_defs) or definition_count
        has_dominant = any(v["is_dominant"] for v in detail)
        if definition_count < 2:
            dominance = "singular"
        elif not usage_measured:
            dominance = "unmeasured"
        elif has_dominant:
            dominance = "dominant"
        else:
            dominance = "contested"
        ranked.append((g, dominance, disagreeing, definition_count, len(detail)))
    ranked.sort(key=lambda t: (_DOMINANCE_ORDER[t[1]], -t[2], -t[3], -t[4],
                               t[0]["canonical_label"] or ""))
    return [t[0] for t in ranked]


def resolve_material_disagreement(store, run_id, executor, period,
                                  tolerance=0.005, function="SUM", now=None,
                                  max_groups=DEFAULT_MAX_GROUPS,
                                  max_queries=DEFAULT_MAX_QUERIES):
    # type: (object, str, object, str, float, str, Optional[str], int, int) -> dict
    """Execute the executable variants of the top metric groups and record the
    gap against each group's reference variant. Gated on VDS availability; writes
    `variant_execution` rows and a `material_disagreement` coverage row.

    Groups are taken in the report's contested-first priority order and bounded
    by a budget: at most `max_groups` groups, and at most `max_queries` VDS
    queries, whichever binds first. The cap is **group-atomic** -- a group's
    reference and its diffs are only meaningful together, so a group is never
    half-run: the first group whose executable variants would cross the query
    budget stops the loop, and every remaining (lower-priority) group is left
    un-run. Un-run groups get no `variant_execution` rows, so the report shows
    them without execution figures (never as "agreeing"), and the coverage row is
    recorded `partial` naming the cap so the scoping is explicit.

    Returns a small summary dict for the CLI/log."""
    summary = {"executed": 0, "groups": 0, "material_groups": 0,
               "skipped": not executor.available, "capped": None,
               "max_groups": max_groups, "max_queries": max_queries}
    if not executor.available:
        # Unmeasured, not clean: the report must show this dimension was not run.
        store.record_coverage(
            run_id, "material_disagreement", "skipped",
            "VizQL Data Service not available on this site")
        return summary

    now = now or (datetime.datetime.utcnow().isoformat() + "Z")
    store.clear_variant_execution(run_id)

    any_error = False
    queries_run = 0
    capped = None
    for g in _ordered_groups(store, run_id):
        gid = g["group_id"]
        rows = store.variant_execution_input(run_id, gid)
        if not rows:
            continue
        classed = [(r,) + classify_variant(r) for r in rows]
        n_exec = sum(1 for _r, cls, _reason in classed if cls == EXECUTABLE)

        # Group-atomic budget. Stop once `max_groups` groups have run, or the
        # next group's queries would cross `max_queries`. A group with no
        # executable variants (n_exec == 0) sends nothing, so it never trips the
        # query cap; it still counts toward the group cap as one of the top N.
        if summary["groups"] >= max_groups:
            capped = "group cap reached (max_groups=%d)" % max_groups
            break
        if n_exec and queries_run + n_exec > max_queries:
            capped = "query cap reached (max_queries=%d)" % max_queries
            break
        queries_run += n_exec

        summary["groups"] += 1

        # Execute every executable variant once (reference included), caching the
        # returned figure by field so the diff pass below is pure arithmetic.
        values = {}  # type: dict
        for r, cls, _reason in classed:
            if cls != EXECUTABLE:
                continue
            res = executor.execute_measure(
                r["datasource_luid"], r["field_name"],
                function=vds_function(r["resolved_formula"], function))
            values[r["field_id"]] = res.value(r["field_name"]) if res.ok else None
            if not res.ok:
                any_error = True

        # Pick the reference only now that execution is done, so a baseline whose
        # own query failed/returned None is passed over for one that produced a
        # value (see _pick_reference). Otherwise a single failed reference query
        # would NULL every diff and hide real disagreement in the group.
        ref_row = _pick_reference(classed, values)
        ref_value = values.get(ref_row["field_id"]) if ref_row is not None else None

        material_here = False
        for r, cls, reason in classed:
            is_ref = ref_row is not None and r["field_id"] == ref_row["field_id"]
            value = None
            abs_diff = rel_diff = None
            material = None
            if cls == EXECUTABLE:
                summary["executed"] += 1
                value = values.get(r["field_id"])
                if value is not None and ref_value is not None:
                    abs_diff = abs(value - ref_value)
                    if ref_value != 0:
                        rel_diff = abs_diff / abs(ref_value)
                    elif abs_diff == 0:
                        rel_diff = 0.0
                    if rel_diff is not None:
                        material = rel_diff > tolerance
                        if material and not is_ref:
                            material_here = True
            store.save_variant_execution(
                run_id, gid, r["field_id"],
                executability_class=cls, untested_reason=(reason or None),
                is_reference=is_ref, period=period, context_applied=False,
                value=value, abs_diff=abs_diff, rel_diff=rel_diff,
                material=material, executed_at=now)
        if material_here:
            summary["material_groups"] += 1

    summary["capped"] = capped
    # A budget-capped run resolved only the top of the backlog, so the dimension
    # is `partial`, never `ok`: the report must not read the un-run groups as
    # agreeing. A run that finished the backlog is `ok` (or `partial` if a query
    # errored). The reason carries the counts and the binding cap either way.
    scope = ("resolved the top %d group(s) in contested-first order using %d "
             "quer%s" % (summary["groups"], queries_run,
                         "y" if queries_run == 1 else "ies"))
    if capped:
        status = "partial"
        reason = "%s: %s; lower-priority groups were not run" % (capped, scope)
        if any_error:
            reason += "; some VDS queries also failed (see variant_execution)"
    elif any_error:
        status = "partial"
        reason = "some VDS queries failed; see variant_execution"
    else:
        status = "ok"
        reason = ("%s against period %s (tolerance %g)"
                  % (scope, period, tolerance))
    store.record_coverage(run_id, "material_disagreement", status, reason)
    store.commit()
    return summary
