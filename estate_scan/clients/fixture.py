"""Offline client: replays a fixture estate as API response envelopes.

Satisfies the same `EstateClient` interface as the live clients, so the whole
pipeline runs against fixtures with no network access and never knows which
backend it is talking to (build brief section 4).

Two invariants:

  * The envelope shape matches the versioned query's selection set exactly, so a
    fixture exercises the same parsing path the live client will.
  * Ground-truth keys (`_concept`, `_view_count`, ...) are NEVER projected into
    a response. Projection is explicit per query, so the answer key the
    generator embedded cannot reach the derivation pipeline.

Partial-response hook: `partial_over={"workbooks": 50}` makes any page request
for that query with `first > 50` come back as a NODE_LIMIT_EXCEEDED partial
carrying a truncated page. The extract runner must subdivide (shrink `first`)
and retry rather than accept it -- this is what tests/test_partial.py drives.
"""

import json
from typing import Callable, Dict, List, Optional

from estate_scan.clients.base import EstateClient, GraphQLResult, RestResult, classify_graphql


class FixtureClient(EstateClient):
    def __init__(self, estate, partial_over=None):
        # type: (dict, Optional[Dict[str, int]]) -> None
        self._estate = estate
        self._partial_over = partial_over or {}
        meta = estate.get("meta", {})
        self.deployment_type = meta.get("deployment_type", "cloud")
        self.adoption_source = meta.get("adoption_source", "fixture")
        site = meta.get("site", {})
        self.site_id = site.get("luid")
        self.site_name = site.get("name")
        # Precompute downstream-workbook counts per data source (by id and luid).
        self._downstream = {}  # type: Dict[str, int]
        for wb in estate.get("workbooks", []):
            for up in wb.get("upstreamDatasources", []):
                for key in (up.get("id"), up.get("luid")):
                    if key:
                        self._downstream[key] = self._downstream.get(key, 0) + 1
        # Index workbooks by luid so a field's usage linkage (from the hidden
        # ground-truth `_used_in_workbooks`) can be projected as the real API's
        # referencedBySheets -> workbook shape. The linkage IS a raw estate fact
        # the Metadata API exposes; the *view counts* are not, so we never expose
        # `_view_count` -- the pipeline recomputes it by joining to usage_events.
        self._wb_by_luid = {}  # type: Dict[str, dict]
        for wb in estate.get("workbooks", []):
            if wb.get("luid"):
                self._wb_by_luid[wb["luid"]] = wb
            if wb.get("id"):
                self._wb_by_luid[wb["id"]] = wb

    # -- construction helpers ------------------------------------------------
    @classmethod
    def from_path(cls, estate_json_path, partial_over=None):
        # type: (str, Optional[Dict[str, int]]) -> FixtureClient
        with open(estate_json_path, "r") as fh:
            return cls(json.load(fh), partial_over=partial_over)

    # -- capability detection ------------------------------------------------
    def detect_capabilities(self):
        # type: () -> Dict[str, bool]
        self.capabilities = {
            "metadata_api": True,
            "rest_jobs": True,           # refresh/job history served by the fixture
            "rest_tasks": True,          # extract-refresh tasks served by the fixture
            "admin_insights": False,     # usage served via the fixture instead
            "repository": False,
            "vizql_data_service": False,
            "data_quality_api": False,
        }
        return self.capabilities

    def run_config(self):
        # type: () -> dict
        """Config the specialist would otherwise supply (domains, target stages,
        declared core metrics). The fixture carries it so scan/score run offline."""
        meta = self._estate.get("meta", {})
        return {
            "core_metrics": meta.get("core_metrics", []),
            "domains": meta.get("domains", []),
            "deployment_type": self.deployment_type,
            "adoption_source": self.adoption_source,
            "site": meta.get("site", {}),
        }

    # -- projections (public shape only) ------------------------------------
    @staticmethod
    def _p_project(p):
        return {"id": p["id"], "name": p["name"],
                "parentProjectName": p.get("parentProjectName")}

    def _p_datasource(self, ds):
        public_field_count = len(ds.get("fields", []))
        dc = self._downstream.get(ds.get("luid")) or self._downstream.get(ds.get("id")) or 0
        return {
            "id": ds["id"], "luid": ds["luid"], "name": ds["name"],
            "projectName": ds.get("projectName"),
            "isCertified": ds.get("isCertified", False),
            "certificationNote": ds.get("certificationNote", ""),
            "owner": {"username": ds.get("owner", {}).get("username"),
                      "email": ds.get("owner", {}).get("email", "")},
            "hasExtracts": ds.get("hasExtracts", False),
            "fieldsConnection": {"totalCount": public_field_count},
            "upstreamTables": [
                {"id": t.get("id"), "name": t.get("name"),
                 "schema": t.get("schema"), "fullName": t.get("fullName")}
                for t in ds.get("upstreamTables", [])],
            "upstreamDatasources": [
                {"id": u.get("id"), "luid": u.get("luid"), "name": u.get("name")}
                for u in ds.get("upstreamDatasources", [])],
            "downstreamWorkbooksConnection": {"totalCount": dc},
        }

    @staticmethod
    def _p_workbook(wb):
        return {
            "id": wb["id"], "luid": wb["luid"], "name": wb["name"],
            "projectName": wb.get("projectName"),
            "createdAt": wb.get("createdAt"), "updatedAt": wb.get("updatedAt"),
            "owner": {"username": wb.get("owner", {}).get("username"),
                      "email": wb.get("owner", {}).get("email", "")},
            "upstreamDatasources": [
                {"id": u.get("id"), "luid": u.get("luid"), "name": u.get("name")}
                for u in wb.get("upstreamDatasources", [])],
            "embeddedDatasources": [
                {"id": e.get("id"), "name": e.get("name")}
                for e in wb.get("embeddedDatasources", [])],
            "sheets": [{"id": s.get("id"), "name": s.get("name")}
                       for s in wb.get("sheets", [])],
            "dashboards": [{"id": d.get("id"), "name": d.get("name")}
                           for d in wb.get("dashboards", [])],
        }

    @staticmethod
    def _p_customsql(cs):
        # Public shape of a CustomSQLTable node. `query` carries the raw SQL --
        # treated like formula text downstream (full in the working build,
        # redacted from the presentation build). `_`-prefixed fixture keys never
        # leak out.
        return {
            "id": cs["id"], "name": cs.get("name"),
            "query": cs.get("query", ""),
            "downstreamDatasources": [
                {"id": d.get("id"), "luid": d.get("luid"), "name": d.get("name")}
                for d in cs.get("downstreamDatasources", [])],
        }

    def _sheets_used_in(self, field):
        # Build referencedBySheets from the hidden usage linkage: one entry per
        # referencing workbook, carrying that workbook's first sheet. The join to
        # usage_events is by workbook, so one entry per workbook is faithful.
        out = []
        for wb_ref in field.get("_used_in_workbooks", []):
            wb = self._wb_by_luid.get(wb_ref)
            if wb is None:
                continue
            sheets = wb.get("sheets") or [{}]
            sheet = sheets[0]
            out.append({
                "id": sheet.get("id"),
                "name": sheet.get("name"),
                "workbook": {"id": wb.get("id"), "luid": wb.get("luid")},
            })
        return out

    def _p_field(self, f):
        node = {
            "__typename": f.get("__typename"),
            "id": f["id"], "name": f["name"],
            "description": f.get("description", ""),
            "isHidden": f.get("isHidden", False),
        }
        if f.get("__typename") == "CalculatedField":
            node["formula"] = f.get("formula")
            node["dataType"] = f.get("dataType")
            node["role"] = f.get("role")
            node["sheetsUsedIn"] = self._sheets_used_in(f)
        elif f.get("__typename") == "ColumnField":
            node["dataType"] = f.get("dataType")
            node["role"] = f.get("role")
        return node

    # -- pagination ----------------------------------------------------------
    def _connection(self, query_name, conn_key, items, project, variables,
                    include_total=True):
        # type: (str, str, list, Callable, dict, bool) -> GraphQLResult
        first = int(variables.get("first", 200))
        after = variables.get("after")
        start = int(after) if after else 0
        threshold = self._partial_over.get(query_name)
        if threshold is not None and first > threshold:
            # Node limit exceeded: return a truncated, untrustworthy page and a
            # NODE_LIMIT_EXCEEDED warning. The runner must subdivide and retry.
            truncated = items[start:start + threshold]
            conn = {"nodes": [project(x) for x in truncated],
                    "pageInfo": {"hasNextPage": True,
                                 "endCursor": str(start + len(truncated))}}
            if include_total:
                conn["totalCount"] = len(items)
            body = {"data": {conn_key: conn},
                    "errors": [{"message": "Showing partial results. The request "
                                           "exceeded the node limit.",
                                "extensions": {"code": "NODE_LIMIT_EXCEEDED"}}]}
            return classify_graphql(200, body)
        page = items[start:start + first]
        nxt = start + len(page)
        has_next = nxt < len(items)
        conn = {"nodes": [project(x) for x in page],
                "pageInfo": {"hasNextPage": has_next,
                             "endCursor": str(nxt) if has_next else None}}
        if include_total:
            conn["totalCount"] = len(items)
        return classify_graphql(200, {"data": {conn_key: conn}})

    # -- interface -----------------------------------------------------------
    def graphql(self, query_name, variables=None):
        # type: (str, Optional[dict]) -> GraphQLResult
        v = variables or {}
        if query_name == "projects":
            return self._connection("projects", "projectsConnection",
                                    self._estate.get("projects", []),
                                    self._p_project, v)
        if query_name == "published_datasources":
            return self._connection("published_datasources",
                                    "publishedDatasourcesConnection",
                                    self._estate.get("datasources", []),
                                    self._p_datasource, v)
        if query_name == "workbooks":
            return self._connection("workbooks", "workbooksConnection",
                                    self._estate.get("workbooks", []),
                                    self._p_workbook, v)
        if query_name == "custom_sql":
            return self._connection("custom_sql", "customSQLTablesConnection",
                                    self._estate.get("custom_sql", []),
                                    self._p_customsql, v)
        if query_name == "datasource_fields":
            return self._datasource_fields(v)
        return classify_graphql(400, {"error": "unknown query: %s" % query_name})

    def _datasource_fields(self, v):
        # type: (dict) -> GraphQLResult
        ds_id = v.get("dsId")
        ds = next((d for d in self._estate.get("datasources", [])
                   if d["id"] == ds_id or d.get("luid") == ds_id), None)
        if ds is None:
            # empty result set (no matching source), not an error
            body = {"data": {"publishedDatasourcesConnection": {"nodes": []}}}
            return classify_graphql(200, body)
        fields = ds.get("fields", [])
        first = int(v.get("first", 200))
        after = v.get("after")
        start = int(after) if after else 0
        threshold = self._partial_over.get("datasource_fields")
        if threshold is not None and first > threshold:
            truncated = fields[start:start + threshold]
            fconn = {"nodes": [self._p_field(f) for f in truncated],
                     "pageInfo": {"hasNextPage": True,
                                  "endCursor": str(start + len(truncated))},
                     "totalCount": len(fields)}
            node = {"id": ds["id"], "luid": ds["luid"], "name": ds["name"],
                    "fieldsConnection": fconn}
            body = {"data": {"publishedDatasourcesConnection": {"nodes": [node]}},
                    "errors": [{"message": "Showing partial results.",
                                "extensions": {"code": "NODE_LIMIT_EXCEEDED"}}]}
            return classify_graphql(200, body)
        page = fields[start:start + first]
        nxt = start + len(page)
        has_next = nxt < len(fields)
        fconn = {"nodes": [self._p_field(f) for f in page],
                 "pageInfo": {"hasNextPage": has_next,
                              "endCursor": str(nxt) if has_next else None},
                 "totalCount": len(fields)}
        node = {"id": ds["id"], "luid": ds["luid"], "name": ds["name"],
                "fieldsConnection": fconn}
        body = {"data": {"publishedDatasourcesConnection": {"nodes": [node]}}}
        return classify_graphql(200, body)

    def rest(self, resource, params=None):
        # type: (str, Optional[dict]) -> RestResult
        if resource == "usage_events":
            items = [dict(u) for u in self._estate.get("usage_events", [])]
            return RestResult(200, items=items, total_available=len(items),
                              has_more=False, next_page=None,
                              raw={"resource": resource})
        if resource == "extract_refresh_tasks":
            items = [dict(j) for j in self._estate.get("refresh_jobs", [])]
            return RestResult(200, items=items, total_available=len(items),
                              has_more=False, next_page=None,
                              raw={"resource": resource})
        if resource == "permissions":
            items = [dict(p) for p in self._estate.get("permissions", [])]
            return RestResult(200, items=items, total_available=len(items),
                              has_more=False, next_page=None,
                              raw={"resource": resource})
        return RestResult(404, items=[], raw={"error": "unknown resource: %s" % resource})

    def datasource_ids(self):
        # type: () -> List[str]
        """Convenience for the shard planner: the published data source ids to
        scope field extraction over (spec 03 §5.1)."""
        return [d["id"] for d in self._estate.get("datasources", [])]
