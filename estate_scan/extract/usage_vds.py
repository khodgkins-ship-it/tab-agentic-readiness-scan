"""Cloud usage extraction via the VizQL Data Service (Admin Insights).

On Tableau Cloud there is no plain REST endpoint that returns per-workbook view
counts, so `usage_events` cannot be a registered GET (that is why the live REST
path returns a synthetic 501 for it). The real source is **Admin Insights** --
the Tableau-managed published data sources that carry site event history -- read
through the read-only VizQL Data Service as a grouped aggregate: one row per
workbook, carrying its view count and last-viewed date over a bounded window.

This module owns only the Admin Insights specifics (which source, which field
captions, the window) and the mapping from a VDS result to the `usage_events`
row shape the loader already expects. It issues nothing itself beyond the
guarded `VdsExecutor`; the runner orchestrates and records coverage.

Read-only holds by construction: the only body built is a grouped
`query{fields, filters}` aggregate, re-validated by `assert_vds_body_read_only`
inside `LiveClient.vds_query` and admitted by Gate C only to the query-datasource
path. There is no write or raw-SQL surface.

**The field captions below are Admin Insights defaults and must be confirmed
against the target site on the first live run** -- Tableau localises and revises
these managed sources. They are config, not constants: override any of them under
`admin_insights.captions` in the live config. If a caption does not exist on the
source, the query is rejected and the runner records usage as *skipped* with the
rejection reason -- never a wrong or empty read passed off as clean.
"""

import datetime
from typing import Dict, List, Optional, Tuple

from estate_scan.clients.vds import VdsExecutor

# Admin Insights defaults. The event-level source ("TS Events" behind the
# "Admin Insights Starter" project) exposes one row per site event; a view is an
# "Access View" event. Captions are the human field names VDS addresses.
DEFAULT_PROJECT = "Admin Insights"
DEFAULT_DATASOURCE = "Admin Insights Starter"
DEFAULT_WINDOW_DAYS = 90
DEFAULT_CAPTIONS = {
    "workbook_luid": "Item LUID",       # the viewed item's luid (joins workbooks.luid)
    # TS Events carries BOTH "Event Type" (coarse action: Access/Create/Update/
    # Delete) and "Event Name" (the specific event, e.g. "Access View"). A view is
    # the specific event, so filter on "Event Name"="Access View"; "Event Type"=
    # "Access" would over-count (data-source access, downloads, ...). Confirmed
    # against Tableau's Admin Insights TS Events dictionary and a live site (R6).
    "event_type": "Event Name",         # the specific-event field to filter on
    "view_event_value": "Access View",  # the Event Name value that is a view
    "event_date": "Event Date",         # the event timestamp (UTC date grain)
}
# Output-column aliases so COUNT and MAX of the event date do not collide.
_ALIAS_VIEWS = "view_count"
_ALIAS_LAST = "last_event_date"


class AdminInsightsConfig(object):
    """Resolved Admin Insights settings for a run, with defaults applied."""

    __slots__ = ("project_name", "datasource_name", "datasource_luid",
                 "window_days", "captions")

    def __init__(self, project_name, datasource_name, datasource_luid,
                 window_days, captions):
        self.project_name = project_name
        self.datasource_name = datasource_name
        self.datasource_luid = datasource_luid
        self.window_days = window_days
        self.captions = captions

    @classmethod
    def from_config(cls, ai_config):
        # type: (Optional[dict]) -> AdminInsightsConfig
        ai = dict(ai_config or {})
        captions = dict(DEFAULT_CAPTIONS)
        captions.update(ai.get("captions") or {})
        try:
            window = int(ai.get("window_days", DEFAULT_WINDOW_DAYS))
        except (TypeError, ValueError):
            window = DEFAULT_WINDOW_DAYS
        return cls(
            project_name=ai.get("project_name", DEFAULT_PROJECT),
            datasource_name=ai.get("datasource_name", DEFAULT_DATASOURCE),
            datasource_luid=ai.get("datasource_luid"),  # optional explicit override
            window_days=window,
            captions=captions)


def resolve_datasource_luid(store, run_id, ai):
    # type: (object, str, AdminInsightsConfig) -> Tuple[Optional[str], str]
    """Find the Admin Insights source's luid from the already-extracted
    datasources. Returns (luid, note). An explicit `datasource_luid` in config
    wins. Otherwise match by name within the Admin Insights project, then fall
    back to any source in that project. Returns (None, reason) when none match,
    so the caller records an honest skip rather than querying a guess."""
    if ai.datasource_luid:
        return ai.datasource_luid, "configured datasource luid"
    rows = store.datasources_in_project(run_id, ai.project_name)
    if not rows:
        return None, ("no data source found in project %r (Admin Insights not "
                      "published on this site, or a different project name)"
                      % ai.project_name)
    by_name = [r for r in rows if (r["name"] or "").lower() == ai.datasource_name.lower()]
    chosen = by_name[0] if by_name else rows[0]
    if chosen["luid"]:
        how = ("matched %r" % ai.datasource_name) if by_name else (
            "project %r has no source named %r; used %r"
            % (ai.project_name, ai.datasource_name, chosen["name"]))
        return chosen["luid"], how
    return None, ("Admin Insights source %r has no luid to query"
                  % (chosen["name"],))


def build_usage_query(executor, luid, ai, now):
    # type: (VdsExecutor, str, AdminInsightsConfig, str) -> dict
    """Grouped read: view count and last-viewed date per workbook luid, over the
    trailing `window_days`, restricted to view events."""
    caps = ai.captions
    dimensions = [caps["workbook_luid"]]
    measures = [
        (caps["event_date"], "COUNT", _ALIAS_VIEWS),
        (caps["event_date"], "MAX", _ALIAS_LAST),
    ]
    filters = [
        executor.match_filter(caps["event_type"], [caps["view_event_value"]]),
        executor.since_date_filter(caps["event_date"], _window_start(now, ai.window_days)),
    ]
    return executor.build_grouped_query(luid, dimensions, measures, filters)


def map_rows(vds_rows, ai, luid_to_wb_id, now, wb_id_to_luid=None):
    # type: (List[dict], AdminInsightsConfig, Dict[str, str], str, Optional[Dict[str, str]]) -> Tuple[List[dict], dict]
    """Map VDS result rows onto the `usage_events` row shape, rolling views up to
    workbooks.

    Admin Insights logs an "Access View" event against the **view** luid (a
    sheet or dashboard), so a single workbook has one usage row per view. This
    keys each event's `Item LUID` to an internal workbook id via `luid_to_wb_id`
    -- a merged map of {view luid -> workbook id} and {workbook luid -> workbook
    id}, so an event that names either the view or the workbook resolves -- then
    **aggregates by workbook id**: view counts sum, and the workbook's last-viewed
    date is the max across its views. A luid in neither map is dropped (an event
    for a view/workbook we did not extract cannot be scored). `usage_events` is
    keyed (run_id, workbook_id), so this aggregation is required -- emitting one
    row per view would collide on that key and lose all but the last view.

    `user_id` is None -- Admin Insights is read here at per-workbook grain, so
    per-user depth is not derived. `wb_id_to_luid` (optional) supplies each
    workbook's OWN luid for the stored `workbook_luid`; without it that column
    falls back to the event luid (a view luid). Returns (rows, stats): `matched`
    is workbooks with usage, `unmatched` is view rows outside the scan."""
    caps = ai.captions
    luid_cap = caps["workbook_luid"]
    wb_id_to_luid = wb_id_to_luid or {}
    agg = {}          # workbook_id -> {"views": int, "last": str|None, "luid": str}
    unmatched = 0
    for r in vds_rows or []:
        luid = r.get(luid_cap)
        if luid is None:
            continue
        wb_id = luid_to_wb_id.get(luid)
        if wb_id is None:
            unmatched += 1
            continue
        views = _as_int(r.get(_ALIAS_VIEWS)) or 0
        last_date = r.get(_ALIAS_LAST)
        cur = agg.get(wb_id)
        if cur is None:
            agg[wb_id] = {
                "views": views,
                "last": last_date,
                "luid": wb_id_to_luid.get(wb_id, luid),
            }
        else:
            cur["views"] += views
            if _is_later(last_date, cur["last"]):
                cur["last"] = last_date
    rows = []
    for wb_id, a in agg.items():
        rows.append({
            "workbook_id": wb_id,
            "workbook_luid": a["luid"],
            "user_id": None,
            "event_date": a["last"],
            "event_count": a["views"],
            "last_viewed_days_ago": _days_ago(now, a["last"]),
        })
    return rows, {"matched": len(rows), "unmatched": unmatched}


def has_expected_columns(vds_rows, ai):
    # type: (List[dict], AdminInsightsConfig) -> bool
    """True when the result carries the columns the mapping needs. A response
    whose rows lack the workbook-luid dimension or the view-count alias means the
    captions did not resolve as expected -> the caller skips, never loads guesswork.
    An empty result set is *not* a column failure (a quiet site legitimately has
    no views in the window); the caller treats empty-but-shaped as ok."""
    if not vds_rows:
        return True
    first = vds_rows[0]
    return ai.captions["workbook_luid"] in first and _ALIAS_VIEWS in first


# -- small helpers -----------------------------------------------------------

def _window_start(now_iso, window_days):
    # type: (str, int) -> str
    dt = _parse(now_iso) or datetime.datetime.now(datetime.timezone.utc)
    return (dt - datetime.timedelta(days=window_days)).strftime("%Y-%m-%d")


def _days_ago(now_iso, date_str):
    # type: (str, Optional[str]) -> Optional[int]
    now = _parse(now_iso)
    then = _parse(date_str)
    if now is None or then is None:
        return None
    return max(0, (now.date() - then.date()).days)


def _is_later(candidate, current):
    # type: (Optional[str], Optional[str]) -> bool
    """True if `candidate` is a later event date than `current` (the running max
    across a workbook's views). A None current loses to any real date; a None
    candidate never wins; unparseable dates fall back to a string compare so a
    max is still chosen deterministically."""
    if current is None:
        return candidate is not None
    if candidate is None:
        return False
    c, cur = _parse(candidate), _parse(current)
    if c is not None and cur is not None:
        return c > cur
    return candidate > current


def _parse(value):
    # type: (Optional[str]) -> Optional[datetime.datetime]
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            dt = datetime.datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _as_int(value):
    # type: (object) -> Optional[int]
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
