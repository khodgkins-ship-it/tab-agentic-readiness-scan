"""An httpx MockTransport that answers the live client from a fixture estate.

`FixtureTransport` lets the R1 test suite drive the *production* `LiveClient`
entirely offline. It answers the exact HTTP calls the client makes -- version
negotiation, sign-in/out, the Metadata GraphQL POST, and the REST probes -- and
for every content query it delegates to a real `FixtureClient`, returning the
identical response envelope the fixture client builds. Both the live path and
the offline path therefore parse the same bytes through the same
`classify_graphql`, which is what makes the backend-agnostic invariant testable.

The transport is wrapped in `ReadOnlyGuard` by `auth.build_session` just like a
production transport, so tests exercise the shipping read-only guard, not a
stand-in.

Edge cases the plan lists as "cassettes" (sign-in failure, Metadata API
disabled, a 401/SESSION_EXPIRED mid-shard, proactive PAT refresh) are driven by
constructor flags rather than recorded JSON: one honest transport covers every
behaviour with no recording dependency and no second envelope implementation.
"""

import json
import re

import httpx

from estate_scan.clients.fixture import FixtureClient

# Operation name == query name for the fixed query set (verified R1). The probe
# LiveClient issues is `query Probe { __typename }`.
_QUERY_NAMES = frozenset({
    "projects", "published_datasources", "workbooks", "datasource_fields",
    "custom_sql",
})
_LINE_COMMENT = re.compile(r"#[^\n\r]*")
_OP_NAME = re.compile(r"\b(?:query|mutation|subscription)\s+([A-Za-z_]\w*)")

# The one VizQL Data Service endpoint the client POSTs to (R3). Mirrors
# live._VDS_QUERY_PATH; kept as a literal so the transport does not import the
# production client just for a string.
_VDS_QUERY_PATH = "/api/v1/vizql-data-service/query-datasource"

# REST content-list and per-object permission routes the permissions sampler
# (live._collect_permissions) exercises. `_LIST_KEYS` maps the URL plural to the
# (estate key, singular item_key); the singular doubles as the flat-grant
# `object_type`, so it drives both the list and the permissions reconstruction.
_LIST_KEYS = {
    "projects": ("projects", "project"),
    "datasources": ("datasources", "datasource"),
    "workbooks": ("workbooks", "workbook"),
}
_LIST_RE = re.compile(r"/sites/[^/]+/(projects|datasources|workbooks)$")
_PERM_RE = re.compile(
    r"/sites/[^/]+/(projects|datasources|workbooks)/([^/]+)/permissions$")


def _op_name(query_text):
    # type: (str) -> str
    # Strip `#` comments first: the fixed query files carry header comments that
    # mention the word "query", which would otherwise be matched before the real
    # operation line.
    stripped = _LINE_COMMENT.sub("", query_text or "")
    m = _OP_NAME.search(stripped)
    return m.group(1) if m else ""


class FixtureTransport(object):
    """Builds an `httpx.MockTransport` answering the live client from `estate`.

    Flags:
      * ``api_version``       -- what `/api/serverinfo` advertises (Server sites
                                 run older versions; used for the Cloud/Server
                                 negotiation test).
      * ``partial_over``      -- forwarded to the inner `FixtureClient` so a
                                 query over the threshold returns a
                                 NODE_LIMIT_EXCEEDED partial.
      * ``signin_status``     -- non-200 simulates a sign-in failure.
      * ``metadata_available``-- False makes the capability probe fail (403), so
                                 `detect_capabilities` aborts.
      * ``graphql_status``    -- non-200 for content queries; 401 surfaces as
                                 SESSION_EXPIRED (session-expiry test).
      * ``rest_status``       -- status for REST probe GETs (default 403, so the
                                 live capability probe reports rest_jobs/rest_tasks
                                 False even though the fixture client serves them).
      * ``list_status``       -- status for the content-list / per-object
                                 permission GETs (default 200; non-200 simulates
                                 a site that refuses to list objects, so the
                                 permissions sampler fails honestly).
      * ``vds_available``     -- True makes the VDS capability probe (a GET to the
                                 POST-only query-datasource endpoint) answer 405
                                 (service present); False answers 404 (absent).
      * ``vds_values``        -- {"<luid>::<fieldCaption>": number} the VDS query
                                 branch answers aggregate reads from; an unknown
                                 measure returns an empty data row (value None).
    """

    def __init__(self, estate, api_version="3.24", partial_over=None,
                 signin_status=200, metadata_available=True,
                 graphql_status=200, rest_status=403, list_status=200,
                 vds_available=False, vds_values=None):
        self._fc = FixtureClient(estate, partial_over=partial_over)
        self._estate = estate
        meta = estate.get("meta", {})
        site = meta.get("site", {})
        self.site_id = site.get("luid") or "site-fixture"
        self.site_name = site.get("name") or "Fixture Site"
        self.content_url = site.get("contentUrl", "")
        self.user_id = "user-fixture"
        self.api_version = api_version
        self.signin_status = signin_status
        self.metadata_available = metadata_available
        self.graphql_status = graphql_status
        self.rest_status = rest_status
        self.list_status = list_status
        self.vds_available = vds_available
        self._vds_values = vds_values or {}
        self._signin_count = 0
        self.requests = []  # type: list  # (method, path) in call order
        self.transport = httpx.MockTransport(self._handle)

    # -- routing -------------------------------------------------------------
    def _handle(self, request):
        # type: (httpx.Request) -> httpx.Response
        path = request.url.path
        method = request.method.upper()
        self.requests.append((method, path))

        if path == "/api/serverinfo":
            return httpx.Response(200, json={"serverInfo": {
                "restApiVersion": self.api_version,
                "productVersion": {"value": "fixture"}}})
        if path.endswith("/auth/signin"):
            return self._signin()
        if path.endswith("/auth/signout"):
            return httpx.Response(204)
        if path == "/api/metadata/graphql":
            return self._graphql(request)
        if path == _VDS_QUERY_PATH:
            if method == "GET":
                # Capability probe: 405 (present) when VDS is enabled, else 404.
                return httpx.Response(405 if self.vds_available else 404,
                                      json={"error": "method not allowed"})
            if method == "POST":
                return self._vds(request)
        if method == "GET":
            m = _PERM_RE.search(path)
            if m:
                if self.list_status != 200:
                    return httpx.Response(self.list_status,
                                          json={"error": "permissions refused"})
                return self._permissions(m.group(1), m.group(2))
            m = _LIST_RE.search(path)
            if m:
                if self.list_status != 200:
                    return httpx.Response(self.list_status,
                                          json={"error": "listing refused"})
                return self._object_list(m.group(1))
            # Everything else (the jobs/tasks capability probes) stays a plain
            # probe failure so rest_jobs/rest_tasks report False, unchanged.
            return httpx.Response(
                self.rest_status,
                json={"error": {"summary": "probe not enabled in fixture"}})
        return httpx.Response(404, json={"error": "unrouted %s %s" % (method, path)})

    # -- REST content lists + per-object permissions -------------------------
    def _object_list(self, plural):
        # type: (str) -> httpx.Response
        estate_key, item_key = _LIST_KEYS[plural]
        objs = self._estate.get(estate_key, []) or []
        items = [{"id": o.get("id"), "name": o.get("name")} for o in objs]
        return httpx.Response(200, json={
            plural: {item_key: items},
            "pagination": {"pageNumber": "1",
                           "pageSize": str(len(items) or 1),
                           "totalAvailable": str(len(items))}})

    def _permissions(self, plural, object_id):
        # type: (str, str) -> httpx.Response
        """Reconstruct the nested Tableau permissions body for one object from
        the fixture's flat grant rows -- grants for the object grouped by grantee
        into granteeCapabilities. The live sampler flattens it straight back, so
        the round-trip is exact (the flat grant PK guarantees uniqueness)."""
        object_type = _LIST_KEYS[plural][1]
        order = []    # type: list  # [(gtype, gid)] in first-seen order
        by_grantee = {}
        for g in self._estate.get("permissions", []) or []:
            if g.get("object_type") != object_type or g.get("object_id") != object_id:
                continue
            gkey = (g.get("grantee_type"), g.get("grantee_id"))
            if gkey not in by_grantee:
                by_grantee[gkey] = []
                order.append(gkey)
            by_grantee[gkey].append(
                {"name": g.get("capability"), "mode": g.get("mode")})
        grantee_capabilities = []
        for (gtype, gid) in order:
            grantee_capabilities.append({
                gtype: {"id": gid},
                "capabilities": {"capability": by_grantee[(gtype, gid)]}})
        return httpx.Response(200, json={"permissions": {
            object_type: {"id": object_id},
            "granteeCapabilities": grantee_capabilities}})

    # -- VizQL Data Service --------------------------------------------------
    def _vds(self, request):
        # type: (httpx.Request) -> httpx.Response
        body = json.loads(request.content.decode("utf-8"))
        luid = (body.get("datasource") or {}).get("datasourceLuid")
        fields = (body.get("query") or {}).get("fields") or []
        caption = fields[0].get("fieldCaption") if fields else None
        key = "%s::%s" % (luid, caption)
        if key in self._vds_values:
            return httpx.Response(200, json={"data": [{caption: self._vds_values[key]}]})
        # Unknown measure -> an empty data row, so `VdsResult.value` reads None.
        return httpx.Response(200, json={"data": [{}]})

    # -- auth ----------------------------------------------------------------
    def _signin(self):
        # type: () -> httpx.Response
        if self.signin_status != 200:
            return httpx.Response(self.signin_status,
                                  json={"error": {"summary": "sign-in refused"}})
        self._signin_count += 1
        return httpx.Response(200, json={"credentials": {
            "token": "tok-%d" % self._signin_count,
            "site": {"id": self.site_id, "contentUrl": self.content_url,
                     "name": self.site_name},
            "user": {"id": self.user_id}}})

    @property
    def signin_count(self):
        # type: () -> int
        return self._signin_count

    # -- GraphQL -------------------------------------------------------------
    def _graphql(self, request):
        # type: (httpx.Request) -> httpx.Response
        body = json.loads(request.content.decode("utf-8"))
        op = _op_name(body.get("query", ""))
        variables = body.get("variables") or {}

        if op == "Probe":
            if not self.metadata_available:
                return httpx.Response(403, json={
                    "errors": [{"message": "Metadata API is not enabled"}]})
            return httpx.Response(200, json={"data": {"__typename": "Query"}})

        if self.graphql_status != 200:
            # 401 -> classify_graphql surfaces SESSION_EXPIRED (never swallowed).
            return httpx.Response(self.graphql_status,
                                  json={"errors": [{"message": "session expired"}]})

        if op in _QUERY_NAMES:
            # Delegate to the fixture client: return the *identical* envelope so
            # the live path parses exactly what the offline path produces.
            raw = self._fc.graphql(op, variables).raw
            return httpx.Response(200, json=raw)

        return httpx.Response(400, json={"error": "unknown operation %r" % op})
