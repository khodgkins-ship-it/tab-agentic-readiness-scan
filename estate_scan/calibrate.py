"""Calibration harness (build brief section 7, section 8; plan R6).

The thresholds that decide when a flag fires are PROVISIONAL. The brief is
explicit that they must NOT be tuned against the synthetic fixtures -- they get
set later, from the real distributions seen across live engagements. This module
is the instrument that emits those distributions.

Given a completed run in the store, `collect_calibration` recomputes -- read
only, mutating nothing -- the four distributions the provisional thresholds sit
on top of:

  * metric-variant count per concept group          (SEM-01 variant_count_gt)
  * usage dominance: top-variant share, top:runner  (rank.py DOMINANCE_MIN_*)
    ratio, and the variant count covering 80% views  (rank.py COVER_FRACTION)
  * refresh freshness: failure rate, and how recently the sources whose latest
    refresh failed were still being viewed             (DF-06, DF-05)
  * permission exposure: sensitive capabilities granted to everyone
                                                        (SEC-02)

Each section is annotated with the threshold that CURRENTLY governs it, pulled
live from `flags/rules.yaml` (and `derive/rank.py` for dominance), so the report
shows the observed distribution next to the line it would be drawn at -- but it
never proposes a new line. Where a section counts how many units sit past the
current threshold, that count is descriptive context for a human calibrating
later; it is not applied and it changes nothing.

Coverage is first-class (invariant 7): a section whose backing measure was not
extracted reports "not measured" with the coverage reason, never an empty
distribution that would read as a clean estate. A metadata-API-only site, for
instance, shows freshness and permission exposure as not measured -- not as zero
exposure.

Offline and deterministic: it reads one run's tables and returns a dict; no
network, no model call, no store mutation.
"""

import datetime
from typing import Dict, List, Optional

from estate_scan.derive.rank import (COVER_FRACTION, DOMINANCE_MIN_RATIO,
                                     DOMINANCE_MIN_SHARE, _cover_count)
from estate_scan.flags.engine import load_rules

# Which coverage measure gates each section. If the measure is not `ok`, the
# section is reported "not measured" rather than computed from partial data --
# an unmeasured dimension must never read as clean (invariant 7).
_GATE_FIELDS = "fields"
_GATE_USAGE = "usage_events"
_GATE_REFRESH = "refresh_jobs"
_GATE_PERMISSIONS = "permissions"


# -- small statistics helpers (stdlib only) ---------------------------------

def _round(x):
    # type: (float) -> float
    return round(x, 3)


def _quantile(sorted_vals, q):
    # type: (List[float], float) -> Optional[float]
    """Linear-interpolated quantile of an already-sorted list. Returns None for
    an empty list; the single value for a one-element list."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _stats(values):
    # type: (List[float]) -> Optional[dict]
    """min / p25 / median / p75 / max / mean over a list of numbers, or None
    when there is nothing to describe."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return {
        "n": n,
        "min": s[0],
        "p25": _round(_quantile(s, 0.25)),
        "median": _round(_quantile(s, 0.5)),
        "p75": _round(_quantile(s, 0.75)),
        "max": s[-1],
        "mean": _round(sum(s) / float(n)),
    }


def _int_histogram(values):
    # type: (List[int]) -> Dict[int, int]
    hist = {}  # type: Dict[int, int]
    for v in values:
        hist[v] = hist.get(v, 0) + 1
    return hist


def _bucketize(values, edges):
    # type: (List[float], List[float]) -> List[dict]
    """Bucket `values` by ascending `edges`. A value belongs to the first bucket
    whose edge it does not exceed (`v <= edge`); the shared boundary belongs to
    the lower bucket. Returns [{range, count}] with human range labels."""
    counts = [0] * (len(edges) + 1)
    for v in values:
        placed = False
        for i, e in enumerate(edges):
            if v <= e:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    out = []  # type: List[dict]
    for i in range(len(edges) + 1):
        if i == 0:
            label = "≤ %g" % edges[0]
        elif i == len(edges):
            label = "> %g" % edges[-1]
        else:
            label = "%g–%g" % (edges[i - 1], edges[i])
        out.append({"range": label, "count": counts[i]})
    return out


# -- collection --------------------------------------------------------------

def _coverage_map(store, run_id):
    # type: (object, str) -> Dict[str, dict]
    return {row["measure"]: {"status": row["status"],
                             "reason": row["reason"] or ""}
            for row in store.coverage(run_id)}


def _gate(coverage, measure):
    # type: (Dict[str, dict], str) -> dict
    """Resolve a section's coverage gate. `measured` is true only when the
    backing measure is present and `ok`; otherwise the reason travels through so
    the report can say why the distribution is absent, not just that it is."""
    entry = coverage.get(measure)
    if entry is None:
        return {"measured": False, "coverage_measure": measure,
                "coverage_status": "absent",
                "coverage_reason": "measure not recorded for this run"}
    return {"measured": entry["status"] == "ok",
            "coverage_measure": measure,
            "coverage_status": entry["status"],
            "coverage_reason": entry["reason"]}


def _variant_count_section(store, run_id, coverage, rules):
    # type: (object, str, Dict[str, dict], dict) -> dict
    section = {
        "key": "metric_variant_count",
        "title": "Metric-variant count per concept group",
        "what": "How many distinct field variants each concept group carries. "
                "The provisional threshold flags a group as fragmented past a "
                "count; the distribution shows where real estates actually sit.",
        "threshold": _threshold(rules, "SEM-01", "variant_count_gt"),
    }
    section.update(_gate(coverage, _GATE_FIELDS))
    if not section["measured"]:
        return section

    counts = [len(store.metric_variants(run_id, g["group_id"]))
              for g in store.metric_groups(run_id)]
    section["n"] = len(counts)
    section["stats"] = _stats(counts)
    section["histogram"] = _int_histogram(counts)
    thr = section["threshold"]
    if thr.get("value") is not None:
        over = sum(1 for c in counts if c > thr["value"])
        section["over_threshold"] = {
            "label": "groups with more than %s variants" % thr["value"],
            "count": over}
    return section


def _dominance_section(store, run_id, coverage):
    # type: (object, str, Dict[str, dict]) -> dict
    section = {
        "key": "usage_dominance",
        "title": "Usage dominance across concept groups",
        "what": "Whether a group's most-used variant dominates. Three views: "
                "the top variant's share of group views, its ratio to the "
                "runner-up, and how many variants it takes to cover 80% of "
                "views. Dominance decides documentation-problem vs "
                "governance-problem, so its thresholds most need real data.",
        # These provisional thresholds live in derive/rank.py, not rules.yaml.
        "threshold": {
            "source": "derive/rank.py",
            "min_share": DOMINANCE_MIN_SHARE,
            "min_ratio": DOMINANCE_MIN_RATIO,
            "cover_fraction": COVER_FRACTION},
    }
    section.update(_gate(coverage, _GATE_USAGE))
    if not section["measured"]:
        return section

    shares = []  # type: List[float]
    ratios = []  # type: List[float]
    cover80 = []  # type: List[int]
    dominant_groups = 0
    groups = store.metric_groups(run_id)
    for g in groups:
        members = store.metric_variants(run_id, g["group_id"])
        sorted_views = sorted((m["view_count"] for m in members), reverse=True)
        total = sum(sorted_views)
        if total <= 0:
            # No measured usage for this group's variants: it contributes to no
            # dominance view rather than a misleading 0-share.
            continue
        shares.append(_round(sorted_views[0] / float(total)))
        if len(sorted_views) >= 2 and sorted_views[1] > 0:
            ratios.append(_round(sorted_views[0] / float(sorted_views[1])))
        cover80.append(_cover_count(sorted_views, COVER_FRACTION))
        if any(m["is_dominant"] for m in members):
            dominant_groups += 1

    section["n"] = len(shares)
    section["dominant_groups"] = dominant_groups
    section["share"] = {
        "stats": _stats(shares),
        "buckets": _bucketize(shares, [0.4, DOMINANCE_MIN_SHARE, 0.8])}
    section["ratio"] = {
        "stats": _stats(ratios),
        "buckets": _bucketize(ratios, [1.5, DOMINANCE_MIN_RATIO, 3.0]),
        "n_with_runner_up": len(ratios)}
    section["cover80"] = {
        "stats": _stats(cover80),
        "histogram": _int_histogram(cover80)}
    return section


def _freshness_section(store, run_id, coverage, rules):
    # type: (object, str, Dict[str, dict], dict) -> dict
    days_thr = _threshold(rules, "DF-05", "viewed_within_days")
    rate_thr = _threshold(rules, "DF-06", "max_failure_rate")
    section = {
        "key": "refresh_freshness",
        "title": "Refresh freshness",
        "what": "The refresh-failure rate across all jobs, and -- for the "
                "sources whose latest refresh failed -- how recently the "
                "workbooks built on them were still viewed. Stale data reaching "
                "recent viewers is the harm the freshness thresholds target.",
        "threshold": {"failure_rate": rate_thr, "viewed_within_days": days_thr},
    }
    section.update(_gate(coverage, _GATE_REFRESH))
    if not section["measured"]:
        return section

    total, failed = store.refresh_job_status_counts(run_id)
    section["jobs_total"] = total
    section["jobs_failed"] = failed
    section["failure_rate"] = _round(failed / float(total)) if total else None

    days = [r["last_viewed_days_ago"]
            for r in store.failed_source_recent_views(run_id)
            if r["last_viewed_days_ago"] is not None]
    section["failed_source_views"] = {
        "n": len(days),
        "stats": _stats(days),
        "buckets": _bucketize(days, [7, 30, 90])}
    if days_thr.get("value") is not None:
        within = sum(1 for d in days if d <= days_thr["value"])
        section["failed_source_views"]["within_current_window"] = {
            "label": "failed-source views within %s days" % days_thr["value"],
            "count": within}
    return section


def _permission_section(store, run_id, coverage, rules):
    # type: (object, str, Dict[str, dict], dict) -> dict
    thr = _threshold(rules, "SEC-02", None)
    everyone = set((thr.get("value") or {}).get("everyone_grantees", []))
    sensitive = set((thr.get("value") or {}).get("sensitive_capabilities", []))
    section = {
        "key": "permission_exposure",
        "title": "Permission exposure",
        "what": "Grants that hand a sensitive capability to an 'everyone' "
                "grantee. The threshold names which grantees count as everyone "
                "and which capabilities count as sensitive; the distribution "
                "shows how much such exposure real estates carry.",
        "threshold": {"everyone_grantees": sorted(everyone),
                      "sensitive_capabilities": sorted(sensitive)},
    }
    section.update(_gate(coverage, _GATE_PERMISSIONS))
    if not section["measured"]:
        return section

    grants = store.permission_grants(run_id)
    section["grants_total"] = len(grants)
    exposed_objects = set()
    by_capability = {}  # type: Dict[str, int]
    permissive = 0
    for g in grants:
        if (g["grantee_id"] in everyone
                and g["capability"] in sensitive
                and (g["mode"] or "") == "Allow"):
            permissive += 1
            exposed_objects.add((g["object_type"], g["object_id"]))
            cap = g["capability"]
            by_capability[cap] = by_capability.get(cap, 0) + 1
    section["permissive_grants"] = permissive
    section["exposed_objects"] = len(exposed_objects)
    section["by_capability"] = by_capability
    return section


def _threshold(rules, flag_id, key):
    # type: (dict, str, Optional[str]) -> dict
    """The current provisional threshold for a flag, read live from rules.yaml.
    `key` picks one field out of the flag's threshold map; None returns the
    whole map. `provisional` travels through so the report can say so."""
    spec = (rules.get("flags", {}) or {}).get(flag_id, {}) or {}
    thr = spec.get("threshold", {}) or {}
    value = thr if key is None else thr.get(key)
    return {"flag": flag_id, "key": key, "value": value, "provisional": True}


def collect_calibration(store, run_id):
    # type: (object, str) -> dict
    """Recompute, read-only, the distributions behind the provisional
    thresholds for one completed run. Mutates nothing and proposes no threshold
    -- it emits the real spread so a human can calibrate later."""
    coverage = _coverage_map(store, run_id)
    rules = load_rules()
    meta = store.run_meta(run_id)
    return {
        "run_id": run_id,
        "site_name": (meta["site_name"] if meta else None),
        "deployment_type": (meta["deployment_type"] if meta else None),
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "coverage": coverage,
        "sections": [
            _variant_count_section(store, run_id, coverage, rules),
            _dominance_section(store, run_id, coverage),
            _freshness_section(store, run_id, coverage, rules),
            _permission_section(store, run_id, coverage, rules),
        ],
    }


# -- rendering ---------------------------------------------------------------

def _fmt(v):
    # type: (object) -> str
    return "—" if v is None else str(v)


def _render_stats_table(a, stats):
    # type: (object, Optional[dict]) -> None
    if not stats:
        a("_No values to summarize._")
        a("")
        return
    a("| n | min | p25 | median | p75 | max | mean |")
    a("|--:|--:|--:|--:|--:|--:|--:|")
    a("| %s | %s | %s | %s | %s | %s | %s |"
      % (stats["n"], _fmt(stats["min"]), _fmt(stats["p25"]),
         _fmt(stats["median"]), _fmt(stats["p75"]), _fmt(stats["max"]),
         _fmt(stats["mean"])))
    a("")


def _render_int_histogram(a, hist, unit):
    # type: (object, Dict[int, int], str) -> None
    if not hist:
        return
    a("| %s | groups |" % unit)
    a("|--:|--:|")
    for k in sorted(hist):
        a("| %s | %s |" % (k, hist[k]))
    a("")


def _render_buckets(a, buckets):
    # type: (object, List[dict]) -> None
    if not buckets:
        return
    a("| range | count |")
    a("|---|--:|")
    for b in buckets:
        a("| %s | %s |" % (b["range"], b["count"]))
    a("")


def _render_not_measured(a, section):
    # type: (object, dict) -> None
    a("> **Not measured.** `%s` coverage is `%s`%s. This distribution is "
      "absent because the data was not collected, not because the estate is "
      "clean." % (section["coverage_measure"], section["coverage_status"],
                  (" — %s" % section["coverage_reason"])
                  if section["coverage_reason"] else ""))
    a("")


def _render_variant_count(a, s):
    # type: (object, dict) -> None
    thr = s["threshold"]
    a("Current provisional threshold: **%s** `%s = %s` (not applied here)."
      % (thr["flag"], thr["key"], _fmt(thr["value"])))
    a("")
    a("Groups measured: %s" % s.get("n", 0))
    a("")
    _render_stats_table(a, s.get("stats"))
    _render_int_histogram(a, s.get("histogram", {}), "variants")
    over = s.get("over_threshold")
    if over:
        a("Observed past the current line (context only): %s = **%s**."
          % (over["label"], over["count"]))
        a("")


def _render_dominance(a, s):
    # type: (object, dict) -> None
    thr = s["threshold"]
    a("Current provisional thresholds (%s): min share **%s**, min ratio "
      "**%s**, cover fraction **%s** (not applied here)."
      % (thr["source"], thr["min_share"], thr["min_ratio"],
         thr["cover_fraction"]))
    a("")
    a("Groups with measured usage: %s (of which currently marked dominant: %s)"
      % (s.get("n", 0), s.get("dominant_groups", 0)))
    a("")
    a("**Top-variant share of group views**")
    a("")
    _render_stats_table(a, s["share"]["stats"])
    _render_buckets(a, s["share"]["buckets"])
    a("**Top-to-runner-up ratio** (groups with a runner-up: %s)"
      % s["ratio"]["n_with_runner_up"])
    a("")
    _render_stats_table(a, s["ratio"]["stats"])
    _render_buckets(a, s["ratio"]["buckets"])
    a("**Variants covering 80% of group views**")
    a("")
    _render_stats_table(a, s["cover80"]["stats"])
    _render_int_histogram(a, s["cover80"]["histogram"], "variants")


def _render_freshness(a, s):
    # type: (object, dict) -> None
    thr = s["threshold"]
    a("Current provisional thresholds: **DF-06** `max_failure_rate = %s`, "
      "**DF-05** `viewed_within_days = %s` (not applied here)."
      % (_fmt(thr["failure_rate"]["value"]),
         _fmt(thr["viewed_within_days"]["value"])))
    a("")
    a("Refresh jobs: %s total, %s failed — failure rate **%s**."
      % (s.get("jobs_total", 0), s.get("jobs_failed", 0),
         _fmt(s.get("failure_rate"))))
    a("")
    fsv = s["failed_source_views"]
    a("**Days since last view, for sources whose latest refresh failed** "
      "(rows: %s)" % fsv["n"])
    a("")
    _render_stats_table(a, fsv["stats"])
    _render_buckets(a, fsv["buckets"])
    within = fsv.get("within_current_window")
    if within:
        a("Observed inside the current window (context only): %s = **%s**."
          % (within["label"], within["count"]))
        a("")


def _render_permissions(a, s):
    # type: (object, dict) -> None
    thr = s["threshold"]
    a("Current provisional threshold: **SEC-02** everyone grantees `%s`, "
      "sensitive capabilities `%s` (not applied here)."
      % (", ".join(thr["everyone_grantees"]) or "—",
         ", ".join(thr["sensitive_capabilities"]) or "—"))
    a("")
    a("Grants recorded: %s. Sensitive-to-everyone grants: **%s**, across **%s** "
      "object(s)." % (s.get("grants_total", 0), s.get("permissive_grants", 0),
                      s.get("exposed_objects", 0)))
    a("")
    by_cap = s.get("by_capability") or {}
    if by_cap:
        a("| capability | permissive grants |")
        a("|---|--:|")
        for cap in sorted(by_cap):
            a("| %s | %s |" % (cap, by_cap[cap]))
        a("")


_RENDERERS = {
    "metric_variant_count": _render_variant_count,
    "usage_dominance": _render_dominance,
    "refresh_freshness": _render_freshness,
    "permission_exposure": _render_permissions,
}


def render_calibration_markdown(summary):
    # type: (dict) -> str
    lines = []  # type: List[str]
    a = lines.append

    a("# Tableau Estate Scan — threshold calibration")
    a("")
    a("- Run: `%s`" % summary["run_id"])
    a("- Site: %s" % (summary.get("site_name") or "unknown"))
    a("- Deployment: %s" % (summary.get("deployment_type") or "unknown"))
    a("- Generated: %s" % summary["generated_at"])
    a("")
    a("> Every flag threshold is **provisional**. This report is the instrument "
      "for setting them from real runs (build brief §7): it shows the "
      "observed distribution next to the line currently drawn. **Nothing here "
      "changes a threshold** — no value below is tuned against this run, and "
      "the \"observed past the line\" counts are context for a human, not a "
      "decision. Thresholds are never calibrated against synthetic fixtures.")
    a("")

    for s in summary["sections"]:
        a("## %s" % s["title"])
        a("")
        a("_%s_" % s["what"])
        a("")
        if not s.get("measured"):
            _render_not_measured(a, s)
            continue
        _RENDERERS[s["key"]](a, s)

    a("---")
    a("_No composite score and no proposed threshold. Distributions only, so a "
      "line can be drawn later from real data rather than from fixtures._")
    a("")
    return "\n".join(lines)
