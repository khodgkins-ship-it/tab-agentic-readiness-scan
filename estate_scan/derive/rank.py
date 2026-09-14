"""Usage ranking and dominance (build spec 7.3, methodology section 5 step 5).

Grouping (group.py) says *which* variants are the same concept. Ranking says
*which one wins*: it orders a group's variants by measured usage and decides
whether one variant is dominant enough that the estate has effectively settled
on it, or whether the concept is genuinely contested.

Dominance is the pivot the whole finding turns on. A concept with one dominant
variant is a documentation problem; a concept with no dominant variant is a
governance problem, and the adjudication backlog is sorted to surface the
latter first (build brief section 6). The rule is configurable and provisional
(build brief section 7 -- do NOT tune against fixtures): a variant is dominant
when it carries at least DOMINANCE_MIN_SHARE of group views AND at least
DOMINANCE_MIN_RATIO times the second-ranked variant.

`variants_covering_80pct_views` (cover80) is the count of top-ranked variants
whose cumulative views first reach 80% of the group -- a plain-language measure
of how concentrated usage is. It is DERIVED on read from the variant rows, not
stored: there is no group-level column for it, so it can never drift from the
variants it summarizes.
"""

from typing import Dict, List, Optional

# Provisional thresholds. Wired to rules.yaml in M5; kept here as the defaults
# the flag engine overrides. Not calibrated against the synthetic fixtures.
DOMINANCE_MIN_SHARE = 0.6
DOMINANCE_MIN_RATIO = 2.0
COVER_FRACTION = 0.8


def _cover_count(sorted_views, fraction):
    # type: (List[int], float) -> int
    """How many top variants it takes for cumulative views to first reach
    `fraction` of the total. 0 when the group has no measured views."""
    total = sum(sorted_views)
    if total <= 0:
        return 0
    target = fraction * total
    cumulative, n = 0, 0
    for v in sorted_views:
        cumulative += v
        n += 1
        if cumulative >= target:
            break
    return n


def _dominant(sorted_views, min_share, min_ratio):
    # type: (List[int], float, float) -> bool
    """Is the top-ranked variant dominant? Needs both a majority share of group
    views and a clear margin over the runner-up. A single-variant group with any
    views is trivially dominant."""
    total = sum(sorted_views)
    if total <= 0 or not sorted_views:
        return False
    top = sorted_views[0]
    if top < min_share * total:
        return False
    if len(sorted_views) == 1:
        return True
    return top >= min_ratio * sorted_views[1]


def rank_groups(store, run_id, min_share=DOMINANCE_MIN_SHARE,
                min_ratio=DOMINANCE_MIN_RATIO, cover_fraction=COVER_FRACTION):
    # type: (object, str, float, float, float) -> dict
    """Rank each group's variants by usage and mark dominance. Persists
    usage_rank / view_count / workbook_count / is_dominant on every variant row
    (via update_variant_usage) and returns an instrumentation summary carrying
    the variant-count and dominance-ratio distributions the build brief asks be
    emitted for later threshold calibration."""
    views = store.field_view_counts(run_id)
    groups = store.metric_groups(run_id)

    detail = []  # type: List[dict]
    variant_counts = []  # type: List[int]
    dominance_ratios = []  # type: List[Optional[float]]
    dominant_groups = 0

    for g in groups:
        group_id = g["group_id"]
        members = store.metric_variants(run_id, group_id)
        # attach measured usage, then order by views desc, field_id asc
        enriched = []
        for m in members:
            vc = views.get(m["field_id"], {})
            enriched.append({
                "field_id": m["field_id"],
                "views": vc.get("views", 0),
                "workbooks": vc.get("workbooks", 0),
            })
        enriched.sort(key=lambda r: (-r["views"], r["field_id"]))

        sorted_views = [r["views"] for r in enriched]
        total = sum(sorted_views)
        is_dom = _dominant(sorted_views, min_share, min_ratio)
        cover80 = _cover_count(sorted_views, cover_fraction)

        for rank, r in enumerate(enriched, start=1):
            store.update_variant_usage(
                run_id, group_id, r["field_id"], rank,
                r["views"], r["workbooks"],
                1 if (rank == 1 and is_dom) else 0)

        # ratio of top to runner-up, for the calibration distribution
        ratio = None  # type: Optional[float]
        if len(sorted_views) >= 2 and sorted_views[1] > 0:
            ratio = round(sorted_views[0] / float(sorted_views[1]), 3)

        variant_counts.append(len(enriched))
        dominance_ratios.append(ratio)
        if is_dom:
            dominant_groups += 1

        detail.append({
            "group_id": group_id,
            "label": g["canonical_label"],
            "variants": len(enriched),
            "group_views": total,
            "cover80": cover80,
            "dominant": is_dom,
            "top_ratio": ratio,
        })

    store.commit()
    return {
        "groups": len(groups),
        "dominant_groups": dominant_groups,
        "thresholds": {"min_share": min_share, "min_ratio": min_ratio,
                       "cover_fraction": cover_fraction},
        # distributions for later threshold-setting (build brief section 7);
        # emitted, not acted on -- the prototype does not tune against these.
        "variant_count_distribution": _histogram(variant_counts),
        "dominance_ratios": [r for r in dominance_ratios if r is not None],
        "detail": detail,
    }


def cover80_for(store, run_id, group_id, cover_fraction=COVER_FRACTION):
    # type: (object, str, str, float) -> int
    """Derive variants_covering_80pct_views for one group from its stored
    variant rows. Not persisted anywhere -- computed on demand so it can never
    disagree with the variants."""
    members = store.metric_variants(run_id, group_id)
    sorted_views = sorted((m["view_count"] for m in members), reverse=True)
    return _cover_count(sorted_views, cover_fraction)


def _histogram(counts):
    # type: (List[int]) -> Dict[int, int]
    hist = {}  # type: Dict[int, int]
    for c in counts:
        hist[c] = hist.get(c, 0) + 1
    return hist
