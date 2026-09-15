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
}

# query name -> coverage measure name
_MEASURE = {
    "projects": "projects",
    "published_datasources": "datasources",
    "workbooks": "workbooks",
    "datasource_fields": "fields",
}

# Global object-level shards, in the dependency order the spec mandates.
_GLOBAL_ORDER = ["projects", "published_datasources", "workbooks"]

# Measures deferred out of the prototype. Recorded as skipped so the report
# renders them as unmeasured -- never as clean (coverage is first-class).
_DEFERRED_MEASURES = [
    ("permissions", "deferred: permissions sampler out of prototype scope"),
    ("refresh_jobs", "deferred: refresh/job history out of prototype scope"),
    ("custom_sql", "deferred: custom SQL extraction out of prototype scope"),
    ("database_tables", "deferred: database table/column extraction out of scope"),
    ("data_quality_warnings", "deferred: DQW extraction out of prototype scope"),
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
            self.client.detect_capabilities()

        # 1-3. Global object shards in dependency order.
        for query_name in _GLOBAL_ORDER:
            hint = queries.shard_hint(query_name)
            shard = global_shard(query_name, hint)
            self._restore(shard)
            ok = self._run_shard(shard)
            self._record_measure(_MEASURE[query_name], shard, ok)

        # 4. Field shards, one per published data source.
        self._run_field_shards()

        # 5. REST usage events (served by the fixture; live source deferred).
        self._run_usage_events()

        # 6. Deferred measures -> skipped, so nothing reads as clean.
        for measure, reason in _DEFERRED_MEASURES:
            self.store.record_coverage(self.run_id, measure, "skipped", reason)

        # 7. Finish + sign out.
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

    # -- usage events --------------------------------------------------------
    def _run_usage_events(self):
        # type: () -> None
        if not hasattr(self.client, "rest"):
            self.store.record_coverage(self.run_id, "usage_events", "skipped",
                                       "no REST transport")
            return
        res = self.client.rest("usage_events")
        if not res.ok:
            self.store.record_coverage(self.run_id, "usage_events", "failed",
                                       "REST status %s" % res.status)
            return
        self.store.load_usage_events(self.run_id, res.items)
        self.store.commit()
        self.store.record_coverage(self.run_id, "usage_events", "ok",
                                   "%d events" % len(res.items))
        self._log("usage_events: loaded %d events" % len(res.items))

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
                self._persist(shard)
                self.store.commit()
                self._log("shard %s FAILED: %s" % (shard.shard_key, res.error))
                return False

            if res.partial:
                # Never accept truncated data. Subdivide and retry same cursor.
                if not shard.can_subdivide():
                    shard.status = "failed"
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
        else:
            raise ValueError("no loader for query %r" % q)

    # -- coverage ------------------------------------------------------------
    def _record_measure(self, measure, shard, ok):
        # type: (str, Shard, bool) -> None
        if ok:
            self.store.record_coverage(self.run_id, measure, "ok",
                                       "%d nodes" % shard.node_count)
        else:
            self.store.record_coverage(self.run_id, measure, "failed",
                                       "shard %s did not complete" % shard.shard_key)
