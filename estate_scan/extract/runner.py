"""Shard planning, resumable execution, and partial-response handling.

The runner walks the fixed query set in dependency order (projects, then
published data sources, then workbooks, then fields per source), paginating each
shard by cursor and persisting shard state after every committed page so a
killed run resumes exactly where it stopped.

The deliverable here is partial-response handling. Every GraphQL response is
classified (clients/base.classify_graphql). A partial response -- data returned
alongside a node-limit warning -- is never accepted: the shard subdivides (page
size halves) and the same cursor is retried until the page comes back complete.
Silently accepting truncated data is the tool's most dangerous failure mode.

The runner issues only reads. Read-only-against-Tableau holds because the client
interface exposes no mutation and this module calls only graphql()/rest().
"""

import datetime
import json
from typing import Callable, List, Optional

from estate_scan import queries
from estate_scan.extract.shards import Shard, global_shard, scoped_shard

# query name -> the connection key in the response envelope
_CONN_KEY = {
    "projects": "projectsConnection",
    "published_datasources": "publishedDatasourcesConnection",
    "workbooks": "workbooksConnection",
    "custom_sql": "customSQLTablesConnection",
    "database_tables": "databaseTablesConnection",
    "data_quality_warnings": "dataQualityWarningsConnection",
}

# query name -> coverage measure name
_MEASURE = {
    "projects": "projects",
    "published_datasources": "datasources",
    "workbooks": "workbooks",
    "datasource_fields": "fields",
    "custom_sql": "custom_sql",
    "database_tables": "database_tables",
    "data_quality_warnings": "data_quality_warnings",
}

# Global object-level shards, in the dependency order the spec mandates.
# custom_sql, database_tables and data_quality_warnings are global GraphQL
# shards (Metadata API), so they ride the same object-shard loop as
# projects/datasources/workbooks -- appended last, in the order they graduated,
# so a resume mid-run through the earlier shards is unchanged.
_GLOBAL_ORDER = ["projects", "published_datasources", "workbooks", "custom_sql",
                 "database_tables", "data_quality_warnings"]

# Measures deferred out of the prototype. Recorded as skipped so the report
# renders them as unmeasured -- never as clean (coverage is first-class).
# permissions / refresh_jobs / custom_sql (R2) and database_tables /
# data_quality_warnings graduated to measured; the rest stay deferred until
# their own milestones.
_DEFERRED_MEASURES = [
    ("query_execution", "full mode only; scan mode never executes queries"),
    ("adoption_trajectory", "retention < 90d; sourced from account records, not the scan"),
]


def _now():
    # type: () -> str
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id():
    # type: () -> str
    return "run_" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")


class ExtractRunner(object):
    def __init__(self, client, store, run_id, page_hook=None):
        # type: (object, object, str, Optional[Callable]) -> None
        self.client = client
        self.store = store
        self.run_id = run_id
        self.page_hook = page_hook
        self.events = []            # type: List[str]
        self.subdivision_events = []  # type: List[tuple]
        self._manifest = queries.load_manifest()
        self._capabilities = {}     # type: dict  # set from detect_capabilities()
        # shard_key -> the fatal error string, so coverage can distinguish a
        # query the site's schema does not support (unavailable) from a query
        # that failed for another reason (failed). Populated in _run_shard.
        self._shard_errors = {}     # type: dict

    # -- logging -------------------------------------------------------------
    def _log(self, msg):
        # type: (str) -> None
        self.events.append("%s %s" % (_now(), msg))

    # -- run -----------------------------------------------------------------
    def run(self):
        # type: () -> None
        cfg = self._run_config()
        self.store.start_run(self.run_id, {
            "site_id": self.client.site_id,
            "site_name": self.client.site_name,
            "deployment_type": self.client.deployment_type,
            "adoption_source": self.client.adoption_source,
            "started_at": _now(),
            "mode": "scan",
            "tool_version": self._manifest.get("tool_version"),
            "query_set_version": self._manifest.get("query_set_version"),
            "model_pass": False,
        })
        self._log("run %s started (query_set=%s)"
                  % (self.run_id, self._manifest.get("query_set_version")))
        if hasattr(self.client, "detect_capabilities"):
            self._capabilities = self.client.detect_capabilities() or {}

        # 1-4. Global object shards in dependency order (custom_sql last).
        for query_name in _GLOBAL_ORDER:
            hint = queries.shard_hint(query_name)
            shard = global_shard(query_name, hint)
            self._restore(shard)
            ok = self._run_shard(shard)
            self._record_measure(_MEASURE[query_name], shard, ok)

        # 5. Field shards, one per published data source.
        self._run_field_shards()

        # 6. REST usage events (adoption + adoption depth via user_id/event_date).
        self._run_usage_events()

        # 7. REST refresh/job history -> freshness (capability-gated on tasks).
        self._run_refresh_jobs()

        # 8. REST permissions sampler (project-level all + content-level sample).
        self._run_permissions()

        # 9. Coverage limitations the client discovered at runtime (e.g. owner
        # attribution gaps on Server). Additive and backend-agnostic -- the
        # fixture client has no such notes.
        self._record_client_notes()

        # 10. Deferred measures -> skipped, so nothing reads as clean.
        for measure, reason in _DEFERRED_MEASURES:
            self.store.record_coverage(self.run_id, measure, "skipped", reason)

        # 11. Finish + sign out.
        cov = {row["measure"]: {"status": row["status"], "reason": row["reason"]}
               for row in self.store.coverage(self.run_id)}
        self.store.finish_run(self.run_id, _now(), json.dumps(cov, sort_keys=True))
        self._log("run %s complete" % self.run_id)
        if hasattr(self.client, "close"):
            self.client.close()

    def _run_config(self):
        # run_config() is part of the EstateClient contract (base returns {}).
        return self.client.run_config()

    # -- field shards --------------------------------------------------------
    def _run_field_shards(self):
        # type: () -> None
        hint = queries.shard_hint("datasource_fields")
        ds_ids = self.store.datasource_ids(self.run_id)
        results = []
        for ds_id in ds_ids:
            shard = scoped_shard("datasource_fields", hint, ds_id)
            self._restore(shard)
            ok = self._run_shard(shard)
            results.append(ok)
        if not results:
            self.store.record_coverage(self.run_id, "fields", "failed",
                                       "no data sources to extract fields from")
            self.store.record_coverage(
                self.run_id, "column_lineage", "skipped",
                "no data sources to project columns from")
            return
        failed = results.count(False)
        if failed == 0:
            self.store.record_coverage(self.run_id, "fields", "ok",
                                       "%d sources" % len(results))
        elif failed < len(results):
            self.store.record_coverage(
                self.run_id, "fields", "partial",
                "%d of %d source field shards failed" % (failed, len(results)))
        else:
            self.store.record_coverage(self.run_id, "fields", "failed",
                                       "all %d field shards failed" % len(results))

        # Column lineage (DF-08) rides on the field shards: ColumnField.
        # upstreamColumns yields the per-source column projection of each root
        # table. It is measurable only when some column-backed field actually
        # carried upstream columns -- an all-calculated estate, or a backend
        # not exposing upstreamColumns, captures none, which must read as
        # unmeasured, never as a clean 'no divergence'.
        proj = self.store.table_column_projection_count(self.run_id)
        if failed == len(results):
            self.store.record_coverage(
                self.run_id, "column_lineage", "skipped",
                "no field shards succeeded; no column projections captured")
        elif proj > 0:
            self.store.record_coverage(
                self.run_id, "column_lineage", "ok",
                "%d column projections captured" % proj)
        else:
            self.store.record_coverage(
                self.run_id, "column_lineage", "skipped",
                "no upstream columns captured (no column-backed fields, or "
                "upstreamColumns unavailable on this backend)")

    # -- usage events --------------------------------------------------------
    def _run_usage_events(self, now=None):
        # type: (Optional[str]) -> None
        """Adoption + adoption-depth from per-workbook view events.

        Two sources, chosen by capability. On Tableau Cloud there is no REST
        endpoint that returns view counts, so when the VizQL Data Service is
        available we read them from Admin Insights as a read-only grouped
        aggregate (`_usage_events_via_vds`). Otherwise -- the fixture path, and
        any site without VDS -- we fall back to the registered REST query
        (`_usage_events_via_rest`), which self-reports its own availability. Both
        paths record honest coverage for every outcome; neither ever loads a
        guess as if it were clean."""
        if self._capabilities.get("vizql_data_service") \
                and hasattr(self.client, "admin_insights"):
            # The VDS path records honest coverage for every outcome (loaded, or
            # a precise skip). We do NOT fall back to REST when it cannot be used:
            # on Cloud there is no REST usage endpoint, and a skip-with-reason is
            # the truthful result -- never a synthetic 501 dressed up as failure.
            self._usage_events_via_vds(now=now or _now())
            return
        self._usage_events_via_rest()

    def _usage_events_via_rest(self):
        # type: () -> None
        if not hasattr(self.client, "rest"):
            self.store.record_coverage(self.run_id, "usage_events", "skipped",
                                       "no REST transport")
            self.store.record_coverage(self.run_id, "adoption_depth", "skipped",
                                       "no usage events to derive per-user depth")
            return
        res = self.client.rest("usage_events")
        if not res.ok:
            self.store.record_coverage(self.run_id, "usage_events", "failed",
                                       "REST status %s" % res.status)
            self.store.record_coverage(self.run_id, "adoption_depth", "skipped",
                                       "usage events unavailable (REST status %s)"
                                       % res.status)
            return
        self.store.load_usage_events(self.run_id, res.items)
        self.store.commit()
        self.store.record_coverage(self.run_id, "usage_events", "ok",
                                   "%d events" % len(res.items))
        self._log("usage_events: loaded %d events" % len(res.items))

        # Adoption depth (ADO-01) rides on the same events: it is measurable only
        # when they carry a per-user identity. If every event's user_id is NULL
        # (the source gave aggregate view counts, not per-user rows) we cannot
        # derive per-user penetration -> skipped, never a clean read.
        with_user = sum(1 for e in res.items if e.get("user_id"))
        if with_user:
            self.store.record_coverage(
                self.run_id, "adoption_depth", "ok",
                "%d of %d events carry a user identity" % (with_user, len(res.items)))
        else:
            self.store.record_coverage(
                self.run_id, "adoption_depth", "skipped",
                "usage events carry no per-user identity (aggregate counts only)")

    def _usage_events_via_vds(self, now=None):
        # type: (Optional[str]) -> None
        """Read per-workbook view counts from Admin Insights over VDS.

        Every exit records coverage first, so the register is never left blank:
        either usage loads `ok`, or it is an honest `skipped` with a precise
        reason (no Admin Insights source, captions that did not resolve, or a VDS
        error). It never falls through to REST -- on Cloud there is no REST usage
        endpoint, so a skip-with-reason is the truthful outcome.

        Adoption depth is always `skipped` on this path: Admin Insights is read at
        per-workbook grain (user_id is None on every mapped row), so per-user
        penetration cannot be derived -- recorded honestly, never as clean."""
        from estate_scan.clients.vds import VdsExecutor
        from estate_scan.extract import usage_vds

        def _skip(reason):
            self.store.record_coverage(self.run_id, "usage_events", "skipped", reason)
            self.store.record_coverage(
                self.run_id, "adoption_depth", "skipped",
                "usage read at per-workbook grain (no per-user identity)")
            self._log("usage_events: skipped (%s)" % reason)

        now = now or _now()
        ai = usage_vds.AdminInsightsConfig.from_config(self.client.admin_insights)
        luid, note = usage_vds.resolve_datasource_luid(self.store, self.run_id, ai)
        if luid is None:
            return _skip("Admin Insights source not resolved: %s" % note)

        executor = VdsExecutor(self.client)
        body = usage_vds.build_usage_query(executor, luid, ai, now)
        try:
            result = self.client.vds_query(body)
        except Exception as exc:  # transport/guard/HTTP -> honest skip, no garbage
            return _skip("VDS query raised %s: %s"
                         % (type(exc).__name__, exc))
        if not result.ok:
            return _skip("VDS query failed (status %s) against %s"
                         % (getattr(result, "status", "?"), note))

        rows = result.data or []
        if not usage_vds.has_expected_columns(rows, ai):
            return _skip("Admin Insights result missing expected columns "
                         "(field captions did not resolve; confirm "
                         "admin_insights.captions for this site)")

        wb_luid_to_id = self.store.workbook_luid_to_id(self.run_id)
        mapped, stats = usage_vds.map_rows(rows, ai, wb_luid_to_id, now)
        self.store.load_usage_events(self.run_id, mapped)
        self.store.commit()
        self.store.set_adoption_source(self.run_id, "admin_insights")

        reason = "%d workbooks with views (%s; source %s)" % (
            stats["matched"], note, ai.datasource_name)
        if stats["unmatched"]:
            reason += "; %d view rows for workbooks outside this scan" % stats["unmatched"]
        self.store.record_coverage(self.run_id, "usage_events", "ok", reason)
        self.store.record_coverage(
            self.run_id, "adoption_depth", "skipped",
            "Admin Insights read at per-workbook grain (no per-user identity)")
        self._log("usage_events: loaded %d workbook usage rows via VDS/Admin Insights"
                  % stats["matched"])

    # -- refresh / job history -----------------------------------------------
    def _run_refresh_jobs(self):
        # type: () -> None
        """Freshness (DF-05/06) from refresh task history. Capability-gated on
        `rest_tasks`: a site without the task/schedule REST surface (e.g. a
        Metadata-only probe, or the offline live path where REST GETs 403) is
        recorded `skipped`, never clean."""
        if not hasattr(self.client, "rest"):
            self.store.record_coverage(self.run_id, "refresh_jobs", "skipped",
                                       "no REST transport")
            return
        if not self._capabilities.get("rest_tasks"):
            self.store.record_coverage(self.run_id, "refresh_jobs", "skipped",
                                       "refresh task/schedule REST API not available")
            return
        res = self.client.rest("extract_refresh_tasks")
        if not res.ok:
            self.store.record_coverage(self.run_id, "refresh_jobs", "failed",
                                       "REST status %s" % res.status)
            return
        self.store.load_refresh_jobs(self.run_id, res.items)
        self.store.commit()
        self.store.record_coverage(self.run_id, "refresh_jobs", "ok",
                                   "%d refresh records" % len(res.items))
        self._log("refresh_jobs: loaded %d records" % len(res.items))

    # -- permissions sampler -------------------------------------------------
    def _run_permissions(self):
        # type: () -> None
        """Permission exposure (SEC-02, governance) via the REST permissions
        surface. Unconditional REST like usage_events: available on the fixture,
        unregistered on the offline live path (-> 501 -> failed), never clean."""
        if not hasattr(self.client, "rest"):
            self.store.record_coverage(self.run_id, "permissions", "skipped",
                                       "no REST transport")
            return
        res = self.client.rest("permissions")
        if not res.ok:
            self.store.record_coverage(self.run_id, "permissions", "failed",
                                       "REST status %s" % res.status)
            return
        self.store.load_permissions(self.run_id, res.items)
        self.store.commit()
        # Surface the sampling basis in the coverage register when the client
        # sampled per object (the live path); the fixture path serves the whole
        # set at once and carries no basis, so its reason is just the count.
        reason = "%d permission grants" % len(res.items)
        basis_text = (res.raw or {}).get("sampling_basis_text") \
            if isinstance(res.raw, dict) else None
        if basis_text:
            reason += " (%s)" % basis_text
        self.store.record_coverage(self.run_id, "permissions", "ok", reason)
        self._log("permissions: loaded %d grants" % len(res.items))

    # -- client-discovered coverage -----------------------------------------
    def _record_client_notes(self):
        # type: () -> None
        notes = getattr(self.client, "coverage_notes", None)
        if not callable(notes):
            return
        for measure, status, reason in notes():
            self.store.record_coverage(self.run_id, measure, status, reason)

    # -- resume --------------------------------------------------------------
    def _restore(self, shard):
        # type: (Shard) -> bool
        row = self.store.get_shard(self.run_id, shard.shard_key)
        if row is None:
            return False
        shard.page_size = row["page_size"]
        shard.cursor = row["cursor"]
        shard.status = row["status"]
        shard.node_count = row["node_count"] or 0
        shard.subdivisions = row["subdivisions"] or 0
        if shard.status == "complete":
            self._log("shard %s already complete, skipping" % shard.shard_key)
        return shard.status == "complete"

    def _persist(self, shard):
        # type: (Shard) -> None
        self.store.save_shard(
            self.run_id, shard.shard_key, shard.query_name, shard.scope_id,
            shard.page_size, shard.cursor, shard.status, shard.node_count,
            shard.subdivisions, _now())

    # -- one shard -----------------------------------------------------------
    def _run_shard(self, shard):
        # type: (Shard) -> bool
        if shard.status == "complete":
            return True
        page_index = 0
        while True:
            res = self.client.graphql(shard.query_name, shard.variables())

            if not res.ok:
                shard.status = "failed"
                self._shard_errors[shard.shard_key] = res.error or ""
                self._persist(shard)
                self.store.commit()
                self._log("shard %s FAILED: %s" % (shard.shard_key, res.error))
                return False

            if res.partial:
                # Never accept truncated data. Subdivide and retry same cursor.
                if not shard.can_subdivide():
                    shard.status = "failed"
                    self._shard_errors[shard.shard_key] = (
                        "partial at minimum page size (single node exceeds "
                        "node limit)")
                    self._persist(shard)
                    self.store.commit()
                    self._log("shard %s FAILED: partial at minimum page size "
                              "(single node exceeds node limit)" % shard.shard_key)
                    return False
                before = shard.page_size
                shard.subdivide()
                shard.status = "in_progress"
                self._persist(shard)
                self.store.commit()
                self.subdivision_events.append(
                    (shard.shard_key, before, shard.page_size))
                self._log("shard %s partial (%s); subdivided page_size %d -> %d"
                          % (shard.shard_key, ",".join(res.warnings),
                             before, shard.page_size))
                continue

            nodes, page_info = self._extract_page(shard, res)
            self._load(shard, nodes)
            shard.node_count += len(nodes)
            if page_info.get("hasNextPage"):
                shard.cursor = page_info.get("endCursor")
                shard.status = "in_progress"
            else:
                shard.status = "complete"
            self._persist(shard)
            self.store.commit()   # rows + shard cursor advance, atomically
            page_index += 1
            if self.page_hook is not None:
                self.page_hook(shard, page_index)   # may raise (simulated kill)
            if shard.status == "complete":
                self._log("shard %s complete: %d nodes, %d subdivisions"
                          % (shard.shard_key, shard.node_count,
                             shard.subdivisions))
                return True

    # -- page extraction + loading ------------------------------------------
    def _extract_page(self, shard, res):
        # type: (Shard, object) -> tuple
        data = res.data or {}
        if shard.query_name == "datasource_fields":
            wrapper = (data.get("publishedDatasourcesConnection") or {}).get("nodes") or []
            if not wrapper:
                return [], {"hasNextPage": False, "endCursor": None}
            fconn = wrapper[0].get("fieldsConnection") or {}
            return fconn.get("nodes") or [], fconn.get("pageInfo") or {}
        conn = data.get(_CONN_KEY[shard.query_name]) or {}
        return conn.get("nodes") or [], conn.get("pageInfo") or {}

    def _load(self, shard, nodes):
        # type: (Shard, list) -> None
        q = shard.query_name
        if q == "projects":
            self.store.load_projects(self.run_id, nodes)
        elif q == "published_datasources":
            self.store.load_datasources(self.run_id, nodes)
        elif q == "workbooks":
            self.store.load_workbooks(self.run_id, nodes)
        elif q == "datasource_fields":
            self.store.load_fields(self.run_id, shard.scope_id, nodes)
        elif q == "custom_sql":
            self.store.load_custom_sql(self.run_id, nodes)
        elif q == "database_tables":
            self.store.load_database_tables(self.run_id, nodes)
        elif q == "data_quality_warnings":
            self.store.load_data_quality_warnings(self.run_id, nodes)
        else:
            raise ValueError("no loader for query %r" % q)

    # -- coverage ------------------------------------------------------------
    # Markers in a GraphQL error message that mean the site's Metadata API
    # schema does not offer the field/type this query selects -- i.e. the
    # measure is *unavailable on this deployment*, not a transient failure.
    # Recording it as "unavailable" (with the reason) rather than "failed"
    # keeps coverage honest: an unmeasured dimension still never reads as clean,
    # but the register distinguishes "your site can't provide this" from
    # "something broke". Kept general so any query that outruns a site's schema
    # degrades the same way, not just projects.
    _SCHEMA_INCOMPAT_MARKERS = (
        "is undefined",            # graphql-java FieldUndefined / WrongType
        "FieldUndefined",
        "Cannot query field",      # graphql-js phrasing
        "Unknown field",
        "Unknown type",
    )

    def _classify_failure(self, shard):
        # type: (Shard) -> tuple
        """Return (status, reason) for a shard that did not complete."""
        err = (self._shard_errors.get(shard.shard_key) or "").strip()
        if err and any(m in err for m in self._SCHEMA_INCOMPAT_MARKERS):
            # Schema validation errors carry no secrets (they name schema
            # types/fields), so surfacing the message is safe and useful.
            return ("unavailable",
                    "not supported by this site's Metadata API schema: %s"
                    % err)
        if err:
            return ("failed", "shard %s did not complete: %s"
                    % (shard.shard_key, err))
        return ("failed", "shard %s did not complete" % shard.shard_key)

    def _record_measure(self, measure, shard, ok):
        # type: (str, Shard, bool) -> None
        if ok:
            self.store.record_coverage(self.run_id, measure, "ok",
                                       "%d nodes" % shard.node_count)
        else:
            status, reason = self._classify_failure(shard)
            self.store.record_coverage(self.run_id, measure, status, reason)
