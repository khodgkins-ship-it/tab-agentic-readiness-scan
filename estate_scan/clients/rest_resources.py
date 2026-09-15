"""Gate B: the REST verb/resource allowlist.

The `EstateClient` REST contract is `rest(resource, params)` -- a *logical
resource name*, never a URL/verb/body. This module is the frozen registry that
name resolves against: logical resource -> `{method, path, item_key, paging}`.
Only reads may register. Registering anything but a `GET` (or a named
read-only POST, of which R1 has none -- VDS is its own executor) raises
`ReadOnlyViolation` at import time, so a would-be write endpoint cannot even be
added by mistake; it fails the build.

There is deliberately no `rest(url, method, body)` escape hatch anywhere in the
client, mirroring the by-name shape the fixture already models. Combined with
Gate A (GraphQL by-name + operation check) and Gate C (the transport guard),
a mutation has no path to the wire.

Path templates carry `{version}` and `{site_id}` placeholders the live client
fills from the negotiated API version and the signed-in site. The registry is
frozen (a read-only mapping) once this module is imported.
"""

from types import MappingProxyType

from estate_scan.readonly import ReadOnlyViolation

__all__ = ["RestResource", "get", "names", "is_registered", "REGISTRY"]

# Only these methods may appear in the registry. GET always; a read-only POST
# would be added here explicitly and reviewed -- R1 has none.
_ALLOWED_METHODS = frozenset({"GET"})


class RestResource(object):
    """One registered read endpoint.

    `paging` is a small descriptor of how the endpoint paginates so the live
    client needs no per-resource code:

      * ``None``                     -- single page, no pagination.
      * ``{"style": "page_number"}`` -- Tableau REST ``pageNumber``/``pageSize``
        query params with a ``pagination`` element in the response body.
    """

    __slots__ = ("name", "method", "path", "item_key", "paging")

    def __init__(self, name, method, path, item_key, paging=None):
        # type: (str, str, str, str, dict) -> None
        method = method.upper()
        if method not in _ALLOWED_METHODS:
            # Fail closed at import time: a write verb never reaches the wire
            # because it cannot be registered in the first place.
            raise ReadOnlyViolation(
                "REST resource %r declares non-read method %r; only %s may register"
                % (name, method, ", ".join(sorted(_ALLOWED_METHODS))))
        self.name = name
        self.method = method
        self.path = path
        self.item_key = item_key
        self.paging = paging

    def __repr__(self):
        return "RestResource(%r, %r, %r)" % (self.name, self.method, self.path)


def _r(name, method, path, item_key, paging=None):
    # type: (str, str, str, str, dict) -> tuple
    return name, RestResource(name, method, path, item_key, paging)


_PAGE = {"style": "page_number"}

# The R1 registry: capability-probe endpoints and content endpoints, all GET.
# usage_events is intentionally absent -- its real source is the VizQL Data
# Service (Cloud) or the repository (Server), wired in R2/R3, not a plain GET.
_REGISTRY = dict([
    # Capability probes (detect_capabilities issues a 1-row read).
    _r("jobs", "GET", "/api/{version}/sites/{site_id}/jobs",
       "backgroundJob", _PAGE),
    _r("extract_refresh_tasks", "GET",
       "/api/{version}/sites/{site_id}/tasks/extractRefreshes", "task", _PAGE),
    # Content endpoints (paginated reads).
    _r("projects", "GET", "/api/{version}/sites/{site_id}/projects",
       "project", _PAGE),
    _r("datasources", "GET", "/api/{version}/sites/{site_id}/datasources",
       "datasource", _PAGE),
    _r("workbooks", "GET", "/api/{version}/sites/{site_id}/workbooks",
       "workbook", _PAGE),
    _r("views", "GET", "/api/{version}/sites/{site_id}/views", "view", _PAGE),
])

#: Frozen, read-only view of the registry (cannot be mutated at runtime).
REGISTRY = MappingProxyType(_REGISTRY)


def get(name):
    # type: (str) -> RestResource
    """Resolve a logical resource name, or raise `KeyError` if unregistered.

    An unregistered name is refused rather than defaulted -- there is no way to
    reach an arbitrary endpoint.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            "unknown REST resource %r; registered: %s"
            % (name, ", ".join(sorted(_REGISTRY))))


def names():
    # type: () -> list
    return sorted(_REGISTRY)


def is_registered(name):
    # type: (str) -> bool
    return name in _REGISTRY
