"""Flag engine (build spec section 8).

Evaluates the declarative catalog in `rules.yaml` against the store and writes
the `flags` table. The engine holds NO thresholds and NO firing logic that a
threshold could express -- all of that lives in the rules file, so the field
team changes what fires without a code edit. Each flag names a `rule`; the
engine dispatches to the evaluator of that name in EVALUATORS below.

An evaluator reads raw measures from the store and its flag's `threshold` block,
and returns whether the flag fires, a salient count, and an evidence dict. The
engine decides emission and scope:

  - implemented: false  -> not evaluated, recorded as unimplemented.
  - suppress: true       -> evaluated anyway (so the log can say whether it WOULD
                            have fired), never written, recorded as suppressed.
  - otherwise            -> written when it fires, once per estate or once per
                            declared domain per `scope`.

The suppression-still-evaluates behaviour is deliberate: a report must never
hide a flag without saying so (build spec section 8), which means knowing the
count it hid.
"""

import datetime
import json
import os
import re
from typing import Dict, List, Optional

import yaml

from estate_scan.derive.group import USER_CONTEXT_FUNCS

RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.yaml")

_UC_RE = re.compile(r"\b(" + "|".join(USER_CONTEXT_FUNCS) + r")\s*\(", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Evaluators. Each returns (fires, count, evidence). Thresholds come from the
# flag's `threshold` block, never hardcoded here.
# ---------------------------------------------------------------------------
def _eval_user_context(store, run_id, th):
    rows = store.calc_field_formulas(run_id)
    hits = [r for r in rows if r["formula"] and _UC_RE.search(r["formula"])]
    count = len(hits)
    fires = count >= th.get("min_count", 1)
    evidence = {"count": count, "fields": [r["name"] for r in hits[:50]]}
    return fires, count, evidence


def _eval_variant_count(store, run_id, th):
    limit = th.get("variant_count_gt", 5)
    fired = {}
    for g in store.metric_groups(run_id):
        n = len(store.metric_variants(run_id, g["group_id"]))
        if n > limit:
            fired[g["canonical_label"]] = n
    fires = len(fired) > 0
    evidence = {"threshold": limit, "groups": sorted(fired.keys()),
                "variant_counts": fired}
    return fires, len(fired), evidence


def _eval_no_dominant(store, run_id, th):
    min_usage = th.get("min_usage_variants", 2)
    fired = []
    for g in store.metric_groups(run_id):
        variants = store.metric_variants(run_id, g["group_id"])
        dominant = any(v["is_dominant"] for v in variants)
        usage_variants = sum(1 for v in variants if (v["view_count"] or 0) > 0)
        if (not dominant) and usage_variants >= min_usage:
            fired.append(g["canonical_label"])
    fires = len(fired) > 0
    evidence = {"min_usage_variants": min_usage, "groups": sorted(fired)}
    return fires, len(fired), evidence


def _eval_description_coverage(store, run_id, th):
    min_cov = th.get("min_coverage", 0.40)
    described, total = store.field_description_coverage(run_id)
    coverage = (described / float(total)) if total else 0.0
    fires = coverage < min_cov
    undescribed = total - described
    evidence = {"coverage": round(coverage, 4), "described": described,
                "total": total, "threshold": min_cov}
    return fires, undescribed, evidence


def _eval_embedded_share(store, run_id, th):
    max_share = th.get("max_embedded_share", 0.60)
    emb, pub = store.workbook_ds_ref_counts(run_id)
    denom = emb + pub
    share = (emb / float(denom)) if denom else 0.0
    fires = share > max_share
    evidence = {"embedded_share": round(share, 4), "embedded_refs": emb,
                "published_refs": pub, "threshold": max_share}
    return fires, emb, evidence


def _eval_upstream_fanout(store, run_id, th):
    limit = th.get("max_sources_per_table", 10)
    rows = store.upstream_table_fanout(run_id)
    over = [{"table": r["upstream_label"] or r["upstream_id"],
             "sources": r["sources"]} for r in rows if r["sources"] > limit]
    max_fanout = rows[0]["sources"] if rows else 0
    fires = len(over) > 0
    evidence = {"max_sources_per_table": max_fanout, "threshold": limit,
                "tables_over_threshold": over}
    # count is the salient fan-out figure (build fixture manifest keys on it)
    return fires, max_fanout, evidence


def _eval_pubon_pub_depth(store, run_id, th):
    min_depth = th.get("min_depth", 2)
    adj = {}  # type: Dict[str, List[str]]
    for e in store.published_on_published_edges(run_id):
        adj.setdefault(e["downstream_id"], []).append(e["upstream_id"])

    def longest(node, seen):
        if node not in adj:
            return 0
        best = 0
        for up in adj[node]:
            if up in seen:
                continue
            best = max(best, 1 + longest(up, seen | {node}))
        return best

    max_depth = max((longest(n, frozenset()) for n in adj), default=0)
    fires = max_depth >= min_depth
    evidence = {"depth": max_depth, "threshold": min_depth}
    return fires, max_depth, evidence


def _eval_zero_view(store, run_id, th):
    min_count = th.get("min_count", 1)
    rows = store.zero_view_workbooks(run_id)
    count = len(rows)
    fires = count >= min_count
    evidence = {"count": count, "idle_days": th.get("idle_days", 90),
                "workbooks": [r["name"] for r in rows[:50]]}
    return fires, count, evidence


def _eval_view_concentration(store, run_id, th):
    fraction = th.get("coverage_fraction", 0.80)
    views = sorted(store.workbook_view_counts(run_id), reverse=True)
    total = sum(views)
    target = fraction * total
    cumulative, n = 0, 0
    for v in views:
        cumulative += v
        n += 1
        if cumulative >= target:
            break
    # Informational: it always reports the concentration when there are views.
    fires = total > 0
    key = "workbooks_covering_%dpct_views" % int(round(fraction * 100))
    evidence = {key: n, "total_views": total, "coverage_fraction": fraction}
    return fires, n, evidence


# -- R4 evaluators (permissions, freshness, grain, provenance, accountability)


def _eval_permissive_grants(store, run_id, th):
    """SEC-02. A permissive grant is an Allow of a sensitive capability to a
    broad 'everyone' grantee. Which grantees count as 'everyone' and which
    capabilities count as sensitive both live in the threshold, so the field
    team retunes this without a code edit and without touching the fixture."""
    everyone = set(th.get("everyone_grantees", ["AllUsers"]))
    sensitive = set(th.get("sensitive_capabilities",
                           ["Write", "Delete", "ChangePermissions", "ProjectLeader"]))
    min_count = th.get("min_count", 1)
    hits = []
    for r in store.permission_grants(run_id):
        if (r["mode"] == "Allow" and r["grantee_id"] in everyone
                and r["capability"] in sensitive):
            hits.append({"object_type": r["object_type"],
                         "object_id": r["object_id"],
                         "grantee": r["grantee_id"],
                         "capability": r["capability"]})
    count = len(hits)
    fires = count >= min_count
    evidence = {"count": count, "everyone_grantees": sorted(everyone),
                "sensitive_capabilities": sorted(sensitive), "grants": hits[:50]}
    return fires, count, evidence


def _eval_datasource_field_count(store, run_id, th):
    """SEM-04. Sources carrying more fields than a person can reason about are an
    exposure-shape problem, not a correctness one. Count = sources over the
    threshold; the salient figure in evidence is the widest source seen."""
    max_fc = th.get("max_field_count", 300)
    rows = store.datasource_field_counts(run_id)
    over = [{"datasource_id": r["datasource_id"], "fields": r["n"]}
            for r in rows if r["n"] > max_fc]
    max_seen = max((r["n"] for r in rows), default=0)
    fires = len(over) > 0
    evidence = {"max_field_count": max_seen, "threshold": max_fc,
                "datasources_over_threshold": over}
    return fires, len(over), evidence


def _eval_source_without_upstream(store, run_id, th):
    """DF-04. Published sources tracing to no upstream at all -- provenance
    cannot be shown for them."""
    min_count = th.get("min_count", 1)
    rows = store.datasources_without_upstream(run_id)
    count = len(rows)
    fires = count >= min_count
    evidence = {"count": count,
                "datasources": [r["name"] or r["id"] for r in rows[:50]]}
    return fires, count, evidence


def _eval_refresh_failure_rate(store, run_id, th):
    """DF-06. Failure rate across the refresh history. Count = failed jobs (the
    salient figure); guarded against an empty history."""
    max_rate = th.get("max_failure_rate", 0.10)
    total, failed = store.refresh_job_status_counts(run_id)
    rate = (failed / float(total)) if total else 0.0
    fires = rate > max_rate
    evidence = {"failure_rate": round(rate, 4), "failed": failed,
                "total": total, "threshold": max_rate}
    return fires, failed, evidence


def _eval_failed_refresh_recent_view(store, run_id, th):
    """DF-05. A source whose LATEST refresh failed while a published workbook
    built on it was viewed within `viewed_within_days` -- broken or stale data
    reaching users. The store returns the raw failed-source/recent-view join;
    the window and firing count live here so both stay in rules.yaml. Count =
    distinct affected sources."""
    within = th.get("viewed_within_days", 30)
    min_count = th.get("min_count", 1)
    sources = {}  # type: Dict[str, set]
    for r in store.failed_source_recent_views(run_id):
        lvd = r["last_viewed_days_ago"]
        if lvd is not None and lvd <= within:
            sources.setdefault(r["datasource_id"], set()).add(r["workbook_id"])
    count = len(sources)
    fires = count >= min_count
    evidence = {"count": count, "viewed_within_days": within,
                "sources": sorted(sources.keys())[:50]}
    return fires, count, evidence


def _eval_custom_sql_grain_loss(store, run_id, th):
    """DF-07 (suppressed by default -- noisy on large estates). Custom SQL with a
    GROUP BY changes the row grain vs the modelled source. Count = tables with a
    GROUP BY; user-function count is carried in evidence but does not fire."""
    min_count = th.get("min_count", 1)
    gb, uf, total = store.custom_sql_grain_counts(run_id)
    fires = gb >= min_count
    evidence = {"with_group_by": gb, "with_user_function": uf,
                "total": total, "threshold": min_count}
    return fires, gb, evidence


def _eval_source_owner_missing(store, run_id, th):
    """GOV-01. A published source with no owner has no accountable party."""
    min_count = th.get("min_count", 1)
    rows = store.datasources_missing_owner(run_id)
    count = len(rows)
    fires = count >= min_count
    evidence = {"count": count,
                "datasources": [r["name"] or r["id"] for r in rows[:50]]}
    return fires, count, evidence


EVALUATORS = {
    "formula_contains_user_context": _eval_user_context,
    "metric_group_variant_count": _eval_variant_count,
    "metric_group_no_dominant": _eval_no_dominant,
    "description_coverage": _eval_description_coverage,
    "embedded_datasource_share": _eval_embedded_share,
    "upstream_table_fanout": _eval_upstream_fanout,
    "published_on_published_depth": _eval_pubon_pub_depth,
    "zero_view_workbooks": _eval_zero_view,
    "view_concentration": _eval_view_concentration,
    "permissive_grants": _eval_permissive_grants,
    "datasource_field_count": _eval_datasource_field_count,
    "source_without_upstream": _eval_source_without_upstream,
    "refresh_failure_rate": _eval_refresh_failure_rate,
    "failed_refresh_recent_view": _eval_failed_refresh_recent_view,
    "custom_sql_grain_loss": _eval_custom_sql_grain_loss,
    "source_owner_missing": _eval_source_owner_missing,
}


# ---------------------------------------------------------------------------
# Engine.
# ---------------------------------------------------------------------------
def load_rules(path=None):
    # type: (Optional[str]) -> dict
    """Load the flag catalog. `path` lets a test point at an alternate file to
    prove threshold changes flow through with no code edit."""
    with open(path or RULES_PATH) as fh:
        return yaml.safe_load(fh)


def _domains_for(scope, domains):
    # type: (str, List[str]) -> List[str]
    """Which domain values a flag writes under. Estate flags write once with an
    empty domain; domain-scoped flags write once per declared domain (or once
    with an empty domain when none are declared)."""
    if scope == "domain" and domains:
        return list(domains)
    return [""]


def evaluate_flags(store, run_id, rules=None, rules_path=None, domains=None,
                   now=None):
    # type: (object, str, Optional[dict], Optional[str], Optional[List[str]], Optional[str]) -> dict
    """Evaluate the catalog against the store and write the `flags` table.

    Returns a summary carrying fired / suppressed / unimplemented / skipped
    lists -- the material the run log needs so a suppressed or unmeasured flag
    is never silently absent.
    """
    if rules is None:
        rules = load_rules(rules_path)
    domains = domains or []
    created_at = now or datetime.datetime.utcnow().isoformat() + "Z"

    store.clear_flags(run_id)
    summary = {"fired": [], "suppressed": [], "unimplemented": [],
               "skipped": []}  # type: Dict[str, list]

    for flag_id in sorted(rules.get("flags", {}).keys()):
        spec = rules["flags"][flag_id]
        if not spec.get("implemented", False):
            summary["unimplemented"].append(flag_id)
            continue

        rule = spec.get("rule")
        evaluator = EVALUATORS.get(rule)
        if evaluator is None:
            # Declared implemented but no evaluator wired: never silently treat
            # as clean -- record it as skipped so coverage stays honest.
            summary["skipped"].append({"flag": flag_id, "reason":
                                       "no evaluator for rule %r" % rule})
            continue

        threshold = spec.get("threshold") or {}
        fires, count, evidence = evaluator(store, run_id, threshold)

        if spec.get("suppress", False):
            summary["suppressed"].append(
                {"flag": flag_id, "would_fire": bool(fires), "count": count})
            continue

        if not fires:
            continue

        for domain in _domains_for(spec.get("scope", "estate"), domains):
            store.save_flag(
                run_id, flag_id, spec.get("severity", "warning"),
                spec.get("confidence", "observed"), spec.get("facet", ""),
                domain, json.dumps(evidence, sort_keys=True), count, created_at)
        summary["fired"].append(
            {"flag": flag_id, "severity": spec.get("severity"),
             "count": count, "facet": spec.get("facet")})

    store.commit()
    return summary


def log_lines(summary):
    # type: (dict) -> List[str]
    """Render the summary as run-log lines. Suppressions and unimplemented flags
    are stated explicitly so the log shows what was NOT emitted and why."""
    lines = []
    for f in summary["fired"]:
        lines.append("FLAG %s [%s] count=%s facet=%s"
                     % (f["flag"], f["severity"], f["count"], f["facet"]))
    for s in summary["suppressed"]:
        lines.append("SUPPRESSED %s (would_fire=%s, count=%s) -- per rules.yaml"
                     % (s["flag"], s["would_fire"], s["count"]))
    for sk in summary["skipped"]:
        lines.append("SKIPPED %s -- %s" % (sk["flag"], sk["reason"]))
    if summary["unimplemented"]:
        lines.append("UNIMPLEMENTED (defined, not evaluated): %s"
                     % ", ".join(summary["unimplemented"]))
    return lines
