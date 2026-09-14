"""The client interface every backend satisfies.

The interface matters more than the implementation. `FixtureClient` (offline
replay) and the live clients (`GraphQLClient`, `RestClient`) all satisfy it, so
every test runs offline and the extraction pipeline never knows which backend it
is using.

Two transport shapes:

  * GraphQL Metadata API  -> `graphql(query_name, variables) -> GraphQLResult`
  * REST API              -> `rest(resource, params)         -> RestResult`

The pipeline addresses queries *by name* against the versioned query set in
`queries/v1`, never by raw query text. That is the load-bearing decision from
the spec: findings must be comparable across reruns and accounts, so a query
can never be generated at runtime.
"""

from typing import Any, Dict, List, Optional


class GraphQLResult(object):
    """The verdict on one GraphQL response.

    The classification mirrors the metadata explorer's `classify_result`
    (app/proxy/tableau_metadata.py), which is the one piece of hard-won API
    logic we deliberately reuse:

      ok=True,  partial=False  -> complete, trustworthy data
      ok=True,  partial=True   -> usable data KNOWN incomplete (a node/time
                                  limit warning came back). The extract layer
                                  must subdivide the shard and retry rather
                                  than accept it.
      ok=False                 -> no usable data; `error` explains why.
    """

    __slots__ = ("ok", "partial", "data", "warnings", "error", "raw")

    def __init__(self, ok, partial, data, warnings=None, error=None, raw=None):
        # type: (bool, bool, Optional[dict], Optional[List[str]], Optional[str], Optional[dict]) -> None
        self.ok = ok
        self.partial = partial
        self.data = data
        self.warnings = warnings or []
        self.error = error
        self.raw = raw

    def __repr__(self):
        return "GraphQLResult(ok=%r, partial=%r, warnings=%r, error=%r)" % (
            self.ok, self.partial, self.warnings, self.error,
        )


class RestResult(object):
    """A REST response: status plus the extracted item list and paging state."""

    __slots__ = ("status", "items", "total_available", "has_more", "next_page", "raw")

    def __init__(self, status, items=None, total_available=0, has_more=False,
                 next_page=None, raw=None):
        # type: (int, Optional[List[dict]], int, bool, Optional[int], Optional[dict]) -> None
        self.status = status
        self.items = items or []
        self.total_available = total_available
        self.has_more = has_more
        self.next_page = next_page
        self.raw = raw

    @property
    def ok(self):
        return 200 <= self.status < 300


class EstateClient(object):
    """Abstract backend. Subclasses implement `graphql` and `rest`."""

    #: capability -> bool, populated by `detect_capabilities`
    capabilities = None  # type: Optional[Dict[str, bool]]

    #: how adoption data was obtained: admin_insights | repository | unavailable
    adoption_source = "unavailable"

    #: cloud | server
    deployment_type = "cloud"

    site_id = None  # type: Optional[str]
    site_name = None  # type: Optional[str]

    def graphql(self, query_name, variables=None):
        # type: (str, Optional[dict]) -> GraphQLResult
        raise NotImplementedError

    def rest(self, resource, params=None):
        # type: (str, Optional[dict]) -> RestResult
        raise NotImplementedError

    def detect_capabilities(self):
        # type: () -> Dict[str, bool]
        raise NotImplementedError

    def close(self):
        # type: () -> None
        """Sign out / release resources. Best-effort, always safe to call."""
        return None


# ---------------------------------------------------------------------------
# GraphQL result classification, ported from tableau-metadata-explorer.
#
# The metadata explorer's tableau_metadata.classify_result() already recognises
# node-limit partial responses. We port the classification (not the whole
# module) so our offline fixture client and the live client share one honest
# notion of "partial". Acting on partial -- subdividing the shard -- is our
# extract layer's job (extract/runner.py); upstream only classifies.
# ---------------------------------------------------------------------------

# Warnings: partial results ARE returned. Keep the data; mark it incomplete.
GQL_WARNING_CODES = frozenset({
    "BACKFILL_RUNNING",
    "NODE_LIMIT_EXCEEDED",
    "TIME_LIMIT_EXCEEDED",
    "MAX_PAGE_SIZE_EXCEEDED",
    "INHERITANCE_INCOMPLETE",
    "LINKED_RESULTS_INCOMPLETE",
    "USER_VISIBILITY_IS_LIMITED",
    "PERMISSIONS_MODE_SWITCHED",
})


def _error_code(err):
    # type: (Any) -> str
    if not isinstance(err, dict):
        return ""
    ext = err.get("extensions") or {}
    return (ext.get("code") or err.get("code") or "").upper()


def classify_graphql(status, body):
    # type: (int, Optional[dict]) -> GraphQLResult
    """Classify a raw (status, json-body) pair into a GraphQLResult.

    Mirrors tableau_metadata.classify_result: a top-level `errors` array on an
    HTTP 200 is normal; a warning code with data present is `partial`, an
    unrecognised code or null data is fatal.
    """
    if status == 401 or (isinstance(body, dict) and body.get("SESSION_EXPIRED")):
        return GraphQLResult(False, False, None, error="SESSION_EXPIRED", raw=body)
    if status != 200:
        msg = body.get("error") if isinstance(body, dict) else None
        return GraphQLResult(False, False, None, error=msg or ("HTTP %d" % status), raw=body)

    gql_data = body.get("data") if isinstance(body, dict) else None
    errors = body.get("errors") if isinstance(body, dict) else None

    if not errors:
        return GraphQLResult(True, False, gql_data, raw=body)

    codes = [c for c in (_error_code(e) for e in errors) if c]
    only_warnings = bool(gql_data) and bool(codes) and all(c in GQL_WARNING_CODES for c in codes)
    if only_warnings:
        return GraphQLResult(True, True, gql_data, warnings=codes, raw=body)

    first_msg = ""
    for e in errors:
        if isinstance(e, dict) and e.get("message"):
            first_msg = e["message"]
            break
    return GraphQLResult(False, False, gql_data,
                         warnings=codes,
                         error=first_msg or (codes[0] if codes else "GraphQL error"),
                         raw=body)
