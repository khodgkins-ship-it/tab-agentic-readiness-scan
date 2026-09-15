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

_MEASURE_ROLE = "measure"
# Same user-context function list SEC-01/grouping use: a resolved formula that
# depends on the viewer (USERNAME(), ISMEMBEROF(), ...) yields a per-viewer value,
# so a single server-side aggregate would be misleading -- context_bound, not run.
_UC_RE = re.compile(r"\b(" + "|".join(USER_CONTEXT_FUNCS) + r")\s*\(",
                    re.IGNORECASE)


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


def _pick_reference(classed):
    # type: (list) -> Optional[object]
    """The baseline variant to diff the others against: the dominant one if any,
    else the executable variant with the best (lowest) usage rank. Only an
    executable variant can be a reference -- a diff against an unrunnable baseline
    would be meaningless. Returns None when nothing is executable."""
    executable = [r for r, cls, _ in classed if cls == EXECUTABLE]
    if not executable:
        return None
    dominant = [r for r in executable if r["is_dominant"]]
    pool = dominant or executable
    return min(pool, key=lambda r: (r["usage_rank"]
                                    if r["usage_rank"] is not None else 1 << 30))


def resolve_material_disagreement(store, run_id, executor, period,
                                  tolerance=0.005, function="SUM", now=None):
    # type: (object, str, object, str, float, str, Optional[str]) -> dict
    """Execute the executable variants of every group and record the gap against
    each group's reference variant. Gated on VDS availability; writes
    `variant_execution` rows and a `material_disagreement` coverage row.

    Returns a small summary dict for the CLI/log."""
    summary = {"executed": 0, "groups": 0, "material_groups": 0,
               "skipped": not executor.available}
    if not executor.available:
        # Unmeasured, not clean: the report must show this dimension was not run.
        store.record_coverage(
            run_id, "material_disagreement", "skipped",
            "VizQL Data Service not available on this site")
        return summary

    now = now or (datetime.datetime.utcnow().isoformat() + "Z")
    store.clear_variant_execution(run_id)

    any_error = False
    for g in store.metric_groups(run_id):
        gid = g["group_id"]
        rows = store.variant_execution_input(run_id, gid)
        if not rows:
            continue
        summary["groups"] += 1
        classed = [(r,) + classify_variant(r) for r in rows]
        ref_row = _pick_reference(classed)

        # Execute every executable variant once (reference included), caching the
        # returned figure by field so the diff pass below is pure arithmetic.
        values = {}  # type: dict
        for r, cls, _reason in classed:
            if cls != EXECUTABLE:
                continue
            res = executor.execute_measure(r["datasource_luid"], r["field_name"],
                                           function=function)
            values[r["field_id"]] = res.value(r["field_name"]) if res.ok else None
            if not res.ok:
                any_error = True
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

    status = "partial" if any_error else "ok"
    reason = ("some VDS queries failed; see variant_execution"
              if any_error else
              "executed against period %s (tolerance %g)" % (period, tolerance))
    store.record_coverage(run_id, "material_disagreement", status, reason)
    store.commit()
    return summary
