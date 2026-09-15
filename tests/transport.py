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
})
_LINE_COMMENT = re.compile(r"#[^\n\r]*")
_OP_NAME = re.compile(r"\b(?:query|mutation|subscription)\s+([A-Za-z_]\w*)")


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
      * ``rest_status``       -- status for REST probe GETs (default 403, which
                                 matches the fixture's rest_jobs/rest_tasks=False).
    """

    def __init__(self, estate, api_version="3.24", partial_over=None,
                 signin_status=200, metadata_available=True,
                 graphql_status=200, rest_status=403):
        self._fc = FixtureClient(estate, partial_over=partial_over)
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
        if method == "GET":
            return httpx.Response(
                self.rest_status,
                json={"error": {"summary": "probe not enabled in fixture"}})
        return httpx.Response(404, json={"error": "unrouted %s %s" % (method, path)})

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
