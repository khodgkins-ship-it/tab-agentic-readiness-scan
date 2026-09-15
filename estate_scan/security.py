"""Gate C (the transport guard) and the secret-hygiene startup check.

`ReadOnlyGuard` wraps *whatever* httpx transport the client is given -- the real
`httpx.HTTPTransport` in production, a `MockTransport` in tests -- so the tests
drive the exact guard that ships. Every outbound request passes through it:

  * `GET`/`HEAD`/`OPTIONS`                 -> allowed (reads).
  * `POST` to the tiny read-POST allowlist -> allowed, with the body re-parsed:
      - Metadata GraphQL: refuse a `mutation`/`subscription` (via `readonly`).
      - VizQL Data Service: refuse a body carrying non-read keys.
      - auth sign-in/sign-out: allowed, body never inspected or logged (it
        carries the PAT secret).
  * anything else (`PUT`/`PATCH`/`DELETE`, or a POST to any other path)
                                           -> `ReadOnlyViolation`, raised hard.

A violation is never caught-and-continued: a write attempt aborts the run. This
lives here (not in `base.py`) so the client base and the offline pipeline stay
httpx-free.

`assert_no_secrets_in_config` is the other half of the security floor: it runs
at the very top of the live path, before any client is constructed, and
hard-aborts (`SystemExit`) if a PAT/secret was put in the config file instead of
the environment or keychain. It names the offending key path but never echoes
the value.
"""

import json
import re

import httpx

from estate_scan.readonly import (
    ReadOnlyViolation,
    assert_graphql_read_only,
    assert_vds_body_read_only,
)

__all__ = ["ReadOnlyGuard", "ReadOnlyViolation", "assert_no_secrets_in_config"]


# -- outbound request allowlist ---------------------------------------------
# Read-only POST endpoints, matched on URL path. The API version segment is a
# wildcard so both Cloud (`3.x`) and any negotiated Server version match.

_SIGNIN = re.compile(r"/api/[\w.\-]+/auth/signin/?$")
_SIGNOUT = re.compile(r"/api/[\w.\-]+/auth/signout/?$")
_METADATA_GRAPHQL = re.compile(r"/api/metadata/graphql/?$")
_VDS_QUERY = re.compile(r"/api/[\w.\-]+/vizql-data-service/query-datasource/?$")

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ReadOnlyGuard(httpx.BaseTransport):
    """An httpx transport wrapper that refuses any write before it reaches the
    inner transport."""

    def __init__(self, inner):
        # type: (httpx.BaseTransport) -> None
        self._inner = inner

    def handle_request(self, request):
        # type: (httpx.Request) -> httpx.Response
        self._assert_allowed(request)
        return self._inner.handle_request(request)

    def close(self):
        # type: () -> None
        closer = getattr(self._inner, "close", None)
        if closer is not None:
            closer()

    # -- the check -----------------------------------------------------------
    def _assert_allowed(self, request):
        # type: (httpx.Request) -> None
        method = request.method.upper()
        if method in _SAFE_METHODS:
            return
        if method != "POST":
            raise ReadOnlyViolation(
                "refusing %s request to %s (only reads are permitted)"
                % (method, request.url.path))

        path = request.url.path
        if _SIGNIN.search(path) or _SIGNOUT.search(path):
            # Auth POST: allowed. Never parse or log the body -- it holds the
            # PAT secret.
            return
        if _METADATA_GRAPHQL.search(path):
            self._assert_graphql_read_only(request)
            return
        if _VDS_QUERY.search(path):
            self._assert_vds_read_only(request)
            return
        raise ReadOnlyViolation(
            "refusing POST to non-allowlisted path %s (not a read endpoint)"
            % path)

    def _assert_graphql_read_only(self, request):
        # type: (httpx.Request) -> None
        body = self._json_body(request, "GraphQL")
        query = body.get("query") if isinstance(body, dict) else None
        if not isinstance(query, str):
            raise ReadOnlyViolation(
                "refusing GraphQL POST with no query string (fail-closed)")
        assert_graphql_read_only(query, label="outbound GraphQL body")

    def _assert_vds_read_only(self, request):
        # type: (httpx.Request) -> None
        body = self._json_body(request, "VDS")
        assert_vds_body_read_only(body, label="outbound VDS body")

    @staticmethod
    def _json_body(request, what):
        # type: (httpx.Request, str) -> dict
        try:
            return json.loads(request.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            # A read endpoint we cannot parse is refused, not waved through.
            raise ReadOnlyViolation(
                "refusing %s POST with an unparseable body (fail-closed)" % what)


# -- secret hygiene ----------------------------------------------------------
# Two defenses. Primary: forbidden key names (near-zero false positives).
# Secondary: a value shaped like a high-entropy PAT secret (conservative).

# Normalized key (lowercased, separators stripped) exactly equal to one of
# these is refused.
_FORBIDDEN_KEYS = frozenset({
    "pat", "token", "secret", "password", "passwd", "pwd",
    "clientsecret", "apikey", "xtableauauth", "authtoken", "accesstoken",
    "personalaccesstokensecret",
})
# ...or a normalized key ending in one of these (catches `pat_secret`,
# `client_secret`, `auth_token`, `x_api_key`, ...). "name" is deliberately not
# here: the PAT *name* is not a secret and may live in config.
_FORBIDDEN_SUFFIXES = ("secret", "password", "token", "apikey")

_KEY_SEP = re.compile(r"[\s_\-]+")
_B64ISH = re.compile(r"^[A-Za-z0-9+/=_\-]{32,}$")


def _norm_key(key):
    # type: (str) -> str
    return _KEY_SEP.sub("", str(key)).lower()


def _key_is_forbidden(key):
    # type: (str) -> bool
    nk = _norm_key(key)
    if nk in _FORBIDDEN_KEYS:
        return True
    return any(nk.endswith(sfx) for sfx in _FORBIDDEN_SUFFIXES)


def _looks_like_secret(value):
    # type: (object) -> bool
    """Conservative high-entropy PAT-secret shape.

    A PAT secret is a long, mixed-class base64-ish token. Requiring all three
    character classes and no URL/path punctuation keeps host names, site content
    URLs, file paths, and lowercase-hex UUIDs from tripping the check.
    """
    if not isinstance(value, str) or not _B64ISH.match(value):
        return False
    has_lower = any(c.islower() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_digit = any(c.isdigit() for c in value)
    return has_lower and has_upper and has_digit


def _abort(message):
    # type: (str) -> None
    # SystemExit (not a plain exception) so the CLI exits non-zero cleanly. The
    # message names the location but NEVER the value.
    raise SystemExit(
        "estate-scan: refusing to run -- " + message
        + " Secrets must come from the environment "
          "(ESTATE_SCAN_PAT_SECRET / ESTATE_SCAN_PAT_NAME) or the OS keychain, "
          "never the config file.")


def assert_no_secrets_in_config(config, _path=""):
    # type: (object, str) -> None
    """Hard-abort (`SystemExit`) if a secret appears in the config.

    Recurses through dicts and lists. Raises on a forbidden key name anywhere,
    or on a value shaped like a high-entropy PAT secret. Idempotent and pure;
    call it before constructing any client.
    """
    if isinstance(config, dict):
        for key, value in config.items():
            here = ("%s.%s" % (_path, key)) if _path else str(key)
            if _key_is_forbidden(key):
                _abort("config key %r looks like a secret." % here)
            if _looks_like_secret(value):
                _abort("config value at %r is shaped like a high-entropy secret."
                       % here)
            assert_no_secrets_in_config(value, here)
    elif isinstance(config, (list, tuple)):
        for i, item in enumerate(config):
            here = "%s[%d]" % (_path, i)
            if _looks_like_secret(item):
                _abort("config value at %r is shaped like a high-entropy secret."
                       % here)
            assert_no_secrets_in_config(item, here)
