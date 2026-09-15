"""The live client: one class for Cloud and Server, over a guarded session.

`LiveClient` satisfies the same `EstateClient` contract as `FixtureClient`, so
the extract runner never knows which backend it is driving. Cloud vs Server is a
*recorded attribute plus a few capability gates*, never a subclass split
(03 §3): sign-in is one shape, the API version is negotiated per host, the one
REST token doubles as `X-Tableau-Auth` for the Metadata API, and the owner
field difference is absorbed by the already-aliased query plus a null-tolerant
loader (the gap is recorded in coverage, never silently treated as clean).

Read-only holds by construction, not convention:
  * Gate A -- `graphql()` resolves text only through the checksum-verified fixed
    query set and calls `queries.assert_read_only(name)` first.
  * Gate B -- `rest()` resolves only names registered GET-only in
    `rest_resources`; there is no `rest(url, method, body)`.
  * Gate C -- every byte leaves through `ReadOnlyGuard` (see `auth.build_session`).

The session refresh is keyed to *elapsed time*, proactively, before a shard --
never a caught 401 (03 §3). A genuine `SESSION_EXPIRED` is surfaced as a failed
result, not silently retried, so a real auth failure is never masked.
"""

import time
from typing import Dict, List, Optional

from estate_scan import queries
from estate_scan.clients import rest_resources
from estate_scan.clients.auth import (
    build_session,
    negotiate_version,
    resolve_credentials,
    signin,
    signout,
)
from estate_scan.clients.base import (
    EstateClient,
    GraphQLResult,
    RestResult,
    VdsResult,
    classify_graphql,
)
from estate_scan.readonly import assert_vds_body_read_only

import httpx

_METADATA_GRAPHQL_PATH = "/api/metadata/graphql"
# The one VizQL Data Service endpoint we ever POST to (R3). It is read-only by
# construction: the body carries a datasource reference plus a read query, and
# Gate C (`ReadOnlyGuard`) admits no other VDS path. The capability probe issues
# a GET here -- a live site answers a GET to this POST-only endpoint with 405,
# which still proves the service is present without needing a datasource LUID.
_VDS_QUERY_PATH = "/api/v1/vizql-data-service/query-datasource"
_OWNER_QUERIES = {
    "workbooks": "workbooksConnection",
    "published_datasources": "publishedDatasourcesConnection",
}


class LiveClient(EstateClient):
    def __init__(self, config, transport=None, clock=None, credentials=None):
        # type: (dict, Optional[httpx.BaseTransport], Optional[object], Optional[object]) -> None
        self._config = dict(config or {})
        self._host = self._config.get("host")
        if not self._host:
            raise ValueError("live config requires a 'host' (the Tableau base URL)")
        self.deployment_type = self._config.get("deployment_type", "cloud")
        self._content_url = self._config.get("site_content_url", "")
        self._timeout = float(self._config.get("timeout_seconds", 60))
        self._refresh_seconds = float(self._config.get("session_refresh_seconds", 3000))
        self._pinned_version = self._config.get("api_version")
        self._clock = clock or time.monotonic

        self._client = build_session(self._host, transport=transport, timeout=self._timeout)
        # Credentials resolved here (env/keychain), held in memory only. The
        # caller runs assert_no_secrets_in_config(config) before this point.
        self._creds = credentials if credentials is not None else resolve_credentials(self._config)

        self._token = None          # type: Optional[str]
        self._api_version = None    # type: Optional[str]
        self._user_id = None        # type: Optional[str]
        self._session_started = None
        self._closed = False

        # Coverage nuance the client discovers (drained by the runner).
        self._objects_seen = 0
        self._owner_missing = 0

        self.capabilities = None    # type: Optional[Dict[str, bool]]
        self.adoption_source = "unavailable"

    # -- lifecycle -----------------------------------------------------------
    def connect(self):
        # type: () -> LiveClient
        """Negotiate the API version and sign in. Idempotent."""
        if self._token is not None:
            return self
        self._api_version = self._pinned_version or negotiate_version(self._client)
        info = signin(self._client, self._api_version, self._content_url, self._creds)
        self._token = info["token"]
        self.site_id = info["site_id"]
        self.site_name = info["site_name"]
        self._content_url = info["site_content_url"] or self._content_url
        self._user_id = info["user_id"]
        self._session_started = self._clock()
        return self

    @property
    def credential_source(self):
        # type: () -> Optional[str]
        """Where the PAT secret came from ("env"|"keyring"). Never the secret."""
        return getattr(self._creds, "source", None)

    @property
    def is_signed_out(self):
        # type: () -> bool
        """True once close() has run: the token has been released locally (and a
        best-effort signout POSTed). Read by the live-smoke summary."""
        return self._closed

    def _auth_headers(self):
        # type: () -> Dict[str, str]
        return {"X-Tableau-Auth": self._token or ""}

    def _maybe_refresh(self):
        # type: () -> None
        """Proactive, elapsed-time-keyed PAT refresh (never a caught 401)."""
        if self._token is None:
            self.connect()
            return
        if self._session_started is None:
            return
        if (self._clock() - self._session_started) >= self._refresh_seconds:
            # Re-sign-in before the server session lapses. Best-effort signout of
            # the old token first; then a fresh sign-in resets the clock.
            old = self._token
            self._token = None
            signout(self._client, self._api_version, old)
            info = signin(self._client, self._api_version, self._content_url, self._creds)
            self._token = info["token"]
            self.site_id = info["site_id"]
            self.site_name = info["site_name"]
            self._user_id = info["user_id"]
            self._session_started = self._clock()

    # -- GraphQL (Gate A) ----------------------------------------------------
    def graphql(self, query_name, variables=None):
        # type: (str, Optional[dict]) -> GraphQLResult
        # Gate A: by-name + read-only operation check, before any I/O.
        queries.assert_read_only(query_name)
        text = queries.load_query(query_name, verify=True)
        self._maybe_refresh()
        try:
            resp = self._client.post(
                _METADATA_GRAPHQL_PATH,
                json={"query": text, "variables": variables or {}},
                headers=self._auth_headers())
        except httpx.HTTPError as exc:
            return GraphQLResult(False, False, None,
                                 error="transport error: %s" % type(exc).__name__)
        result = classify_graphql(resp.status_code, _safe_json(resp))
        self._note_owner(query_name, result)
        return result

    # -- REST (Gate B) -------------------------------------------------------
    def rest(self, resource, params=None):
        # type: (str, Optional[dict]) -> RestResult
        if not rest_resources.is_registered(resource):
            # usage_events and other later-milestone sources are not wired to a
            # live endpoint in R1 (their sources are VDS/repository, R2/R3). Fail
            # unavailable -- never a clean empty result.
            return RestResult(501, items=[],
                              raw={"error": "resource %r not wired to a live "
                                            "source in R1" % resource})
        spec = rest_resources.get(resource)  # Gate B: GET-only registry
        self._maybe_refresh()
        path = spec.path.format(version=self._api_version, site_id=self.site_id)
        return self._rest_get(spec, path, params)

    def _rest_get(self, spec, path, params):
        # type: (object, str, Optional[dict]) -> RestResult
        try:
            resp = self._client.get(path, params=params or {},
                                    headers=self._auth_headers())
        except httpx.HTTPError as exc:
            return RestResult(599, items=[],
                              raw={"error": "transport error: %s" % type(exc).__name__})
        body = _safe_json(resp)
        items, total = _parse_rest_list(body, spec.item_key)
        return RestResult(resp.status_code, items=items, total_available=total,
                          has_more=False, raw=body)

    # -- VizQL Data Service (Gate C) -----------------------------------------
    def vds_query(self, body):
        # type: (dict) -> VdsResult
        """Issue one read-only VizQL Data Service query and parse the result.

        The body is re-validated against the read schema here -- belt to the
        transport guard's braces -- so a hand-built write-shaped body is refused
        at the client too, before any byte leaves. The only POST path is
        query-datasource; the caller (`clients/vds.py`) builds the body from a
        resolved variant + fixed period, so there is no raw-SQL surface.
        """
        assert_vds_body_read_only(body, label="vds_query")
        self._maybe_refresh()
        try:
            resp = self._client.post(_VDS_QUERY_PATH, json=body,
                                     headers=self._auth_headers())
        except httpx.HTTPError as exc:
            return VdsResult(599,
                             error="transport error: %s" % type(exc).__name__)
        return _classify_vds(resp.status_code, _safe_json(resp))

    # -- capabilities --------------------------------------------------------
    def detect_capabilities(self):
        # type: () -> Dict[str, bool]
        metadata_ok = self._probe_metadata()
        caps = {
            "metadata_api": metadata_ok,
            "rest_jobs": self._probe_rest("jobs"),
            "rest_tasks": self._probe_rest("extract_refresh_tasks"),
            # The following light up in later milestones; probed False in R1 so
            # nothing they gate ever reads as clean.
            "admin_insights": False,        # R2: Admin Insights datasources (VDS)
            "repository": False,            # R2: Server repository access
            "vizql_data_service": self._probe_vds(),  # R3: VDS executor
            "data_quality_api": False,      # R4: data-quality warnings
        }
        self.capabilities = caps
        if not metadata_ok:
            # The one capability with no substitute: without the Metadata API the
            # core extraction cannot run. Abort, naming the operator-facing fix.
            raise SystemExit(
                "estate-scan: the Tableau Metadata API is unavailable on %s. On "
                "Tableau Server it must be enabled by an admin (Tableau Metadata "
                "API / Catalog: `tsm maintenance metadata-services enable`). "
                "There is no substitute source for the metadata scan." % self._host)
        return caps

    def _probe_metadata(self):
        # type: () -> bool
        self._maybe_refresh()
        try:
            resp = self._client.post(
                _METADATA_GRAPHQL_PATH,
                json={"query": "query Probe { __typename }", "variables": {}},
                headers=self._auth_headers())
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        body = _safe_json(resp)
        return isinstance(body, dict) and bool(body.get("data"))

    def _probe_vds(self):
        # type: () -> bool
        """Is the VizQL Data Service available on this site? Probed with a GET
        to the (POST-only) query-datasource endpoint: a live site answers 405
        Method Not Allowed when the service is present and 404 when it is not, so
        a 200/405 means present. A GET always passes Gate C and needs no
        datasource LUID. The exact readiness semantics are confirmed against a
        real site at R6; until then the probe is conservative (absent unless the
        endpoint clearly answers)."""
        self._maybe_refresh()
        try:
            resp = self._client.get(_VDS_QUERY_PATH, headers=self._auth_headers())
        except httpx.HTTPError:
            return False
        return resp.status_code in (200, 405)

    def _probe_rest(self, resource):
        # type: (str) -> bool
        if not rest_resources.is_registered(resource):
            return False
        spec = rest_resources.get(resource)
        self._maybe_refresh()
        path = spec.path.format(version=self._api_version, site_id=self.site_id)
        try:
            resp = self._client.get(path, params={"pageSize": 1},
                                    headers=self._auth_headers())
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    # -- config / coverage notes --------------------------------------------
    def run_config(self):
        # type: () -> dict
        return {
            "core_metrics": self._config.get("core_metrics", []),
            "domains": self._config.get("domains", []),
            "deployment_type": self.deployment_type,
            "adoption_source": self.adoption_source,
            "site": {"contentUrl": self._content_url,
                     "id": self.site_id, "name": self.site_name},
            "api_version": self._api_version,
        }

    def _note_owner(self, query_name, result):
        # type: (str, GraphQLResult) -> None
        conn_key = _OWNER_QUERIES.get(query_name)
        if conn_key is None or not result.ok or not result.data:
            return
        nodes = ((result.data.get(conn_key) or {}).get("nodes")) or []
        for node in nodes:
            self._objects_seen += 1
            owner = node.get("owner") or {}
            if not (owner.get("username") or owner.get("email")):
                self._owner_missing += 1

    def coverage_notes(self):
        # type: () -> List[tuple]
        """Coverage limitations the client discovered at runtime.

        Owner attribution is deployment/permission dependent (Server may not
        expose it); reporting the gap keeps it from reading as clean. Drained by
        the extract runner; absent on the fixture client.
        """
        notes = []
        if self._objects_seen and self._owner_missing:
            notes.append((
                "owner_attribution", "partial",
                "owner unavailable on %d of %d objects (deployment/permission "
                "limited)" % (self._owner_missing, self._objects_seen)))
        return notes

    # -- teardown ------------------------------------------------------------
    def close(self):
        # type: () -> None
        """Sign out, null the token, close the client. Idempotent; never raises."""
        if self._closed:
            return
        self._closed = True
        token, self._token = self._token, None
        try:
            signout(self._client, self._api_version, token)
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass


# -- module helpers ----------------------------------------------------------

def _safe_json(resp):
    # type: (httpx.Response) -> dict
    try:
        return resp.json()
    except ValueError:
        return {"error": "non-JSON response (HTTP %d)" % resp.status_code}


def _classify_vds(status, body):
    # type: (int, dict) -> VdsResult
    """Turn a VDS query response into a `VdsResult`. A non-200, a non-dict body,
    or a body missing the `data` array is an error, never usable-but-empty."""
    if status != 200:
        msg = body.get("error") if isinstance(body, dict) else None
        return VdsResult(status, error=(msg if isinstance(msg, str) else None)
                         or ("VDS query returned HTTP %d" % status), raw=body)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return VdsResult(status, error="VDS response missing data array",
                         raw=body if isinstance(body, dict) else None)
    return VdsResult(status, data=data, raw=body)


def _parse_rest_list(body, item_key):
    # type: (dict, str) -> tuple
    """Extract (items, total_available) from a Tableau REST list body.

    Tableau nests as ``{container: {item_key: [...]}, pagination: {...}}`` where
    the container name is irregular per endpoint, so we locate the list by its
    `item_key` wherever it sits. Lenient by design -- the R1 registry uses this
    for capability probes; per-endpoint extraction firms up in R2.
    """
    total = 0
    if isinstance(body, dict):
        pag = body.get("pagination") or {}
        try:
            total = int(pag.get("totalAvailable", 0))
        except (TypeError, ValueError):
            total = 0
        found = _find_item_list(body, item_key)
        if found is not None:
            return found, (total or len(found))
    return [], total


def _find_item_list(node, item_key):
    # type: (object, str) -> Optional[list]
    if isinstance(node, dict):
        if isinstance(node.get(item_key), list):
            return node[item_key]
        for value in node.values():
            found = _find_item_list(value, item_key)
            if found is not None:
                return found
    return None
