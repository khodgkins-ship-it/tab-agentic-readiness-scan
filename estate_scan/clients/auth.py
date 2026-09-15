"""Sign-in / sign-out, API-version negotiation, and credential resolution.

Everything here is deployment-agnostic: Cloud and Server differ only in the
`host`/`site_content_url` config values, not in the sign-in shape (03 §3). The
one REST token returned by sign-in doubles as the `X-Tableau-Auth` header for
the Metadata API and the VizQL Data Service, so there is a single session.

Two seams keep the whole thing offline-testable:

  * `build_session(base_url, transport=None)` -- production passes nothing and
    gets a real `httpx.HTTPTransport`; tests pass a `MockTransport`. Either way
    the transport is wrapped in `ReadOnlyGuard`, so tests drive the exact guard
    that ships.
  * credential resolution reads the environment first (the stdlib floor that
    covers CI) and only then an *optional* `keyring`; the PAT secret never
    touches the config file or the store.
"""

import os

import httpx

from estate_scan.security import ReadOnlyGuard

__all__ = [
    "Credentials",
    "resolve_credentials",
    "build_session",
    "negotiate_version",
    "signin",
    "signout",
    "AuthError",
]

#: Env vars are the credential floor (stdlib, works in CI with no keychain).
ENV_PAT_NAME = "ESTATE_SCAN_PAT_NAME"
ENV_PAT_SECRET = "ESTATE_SCAN_PAT_SECRET"

#: Service name used when looking a secret up in the OS keychain via `keyring`.
KEYRING_SERVICE = "estate-scan"

#: API version used to reach `/api/serverinfo` before negotiation completes, and
#: the fallback when a host does not advertise one. Kept current-ish; the real
#: version is negotiated per host, never assumed (unlike upstream's pinned 3.28).
BOOTSTRAP_API_VERSION = "3.24"


class AuthError(Exception):
    """Sign-in / sign-out failed, or a required credential was absent."""


class Credentials(object):
    """A resolved PAT. `secret` lives in memory only -- never stored or logged."""

    __slots__ = ("pat_name", "secret", "source")

    def __init__(self, pat_name, secret, source):
        # type: (str, str, str) -> None
        self.pat_name = pat_name
        self.secret = secret
        self.source = source  # "env" | "keyring"

    def __repr__(self):
        # Never render the secret.
        return "Credentials(pat_name=%r, source=%r, secret=<redacted>)" % (
            self.pat_name, self.source)


def resolve_credentials(config=None):
    # type: (dict) -> Credentials
    """Resolve the PAT from the environment, then optionally the OS keychain.

    The PAT *name* may come from the environment or (non-secret) config; the
    *secret* comes only from the environment or, if `keyring` is installed, the
    OS keychain -- never from config. Raises `SystemExit` with actionable
    guidance if no secret can be found, so a live run never proceeds unauthed.
    """
    config = config or {}
    pat_name = os.environ.get(ENV_PAT_NAME) or config.get("pat_name")
    secret = os.environ.get(ENV_PAT_SECRET)
    source = "env"

    if not secret:
        secret = _keyring_secret(pat_name)
        if secret:
            source = "keyring"

    if not pat_name or not secret:
        raise SystemExit(
            "estate-scan: no Tableau credentials found. Set %s and %s in the "
            "environment (or store the secret in the OS keychain under service "
            "%r with the PAT name as the username). Credentials are never read "
            "from the config file." % (ENV_PAT_NAME, ENV_PAT_SECRET, KEYRING_SERVICE))
    return Credentials(pat_name, secret, source)


def _keyring_secret(pat_name):
    # type: (str) -> str
    """Best-effort OS-keychain lookup. `keyring` is an optional dependency: if it
    is not installed, degrade cleanly to env-var-only (returns "")."""
    if not pat_name:
        return ""
    try:
        import keyring  # optional dependency; absent in the default footprint
    except Exception:
        return ""
    try:
        return keyring.get_password(KEYRING_SERVICE, pat_name) or ""
    except Exception:
        # A broken/locked keychain backend must not crash the run; env-var floor
        # still applies and the missing-secret guard below will fire if needed.
        return ""


def build_session(base_url, transport=None, timeout=60.0):
    # type: (str, httpx.BaseTransport, float) -> httpx.Client
    """Build the guarded httpx.Client every live request goes through.

    `transport=None` -> real `httpx.HTTPTransport`; a test passes a
    `MockTransport`. Whatever is passed is wrapped in `ReadOnlyGuard`, so the
    read-only transport gate is exercised identically in tests and production.
    """
    inner = transport if transport is not None else httpx.HTTPTransport()
    guarded = ReadOnlyGuard(inner)
    return httpx.Client(
        base_url=base_url,
        transport=guarded,
        timeout=timeout,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )


def negotiate_version(client, default=BOOTSTRAP_API_VERSION):
    # type: (httpx.Client, str) -> str
    """Negotiate the REST API version via `GET /api/serverinfo`.

    This is the fix for upstream's pinned `3.28`: Server sites often run older
    versions, so we ask the host what it speaks. Falls back to `default` if the
    endpoint is unreachable or malformed rather than guessing high.
    """
    try:
        resp = client.get("/api/serverinfo")
    except httpx.HTTPError:
        return default
    if resp.status_code != 200:
        return default
    try:
        info = resp.json().get("serverInfo", {})
    except ValueError:
        return default
    return info.get("restApiVersion") or default


def signin(client, version, content_url, creds):
    # type: (httpx.Client, str, str, Credentials) -> dict
    """POST /api/{version}/auth/signin. Returns {token, site_id, site_content_url,
    user_id}. The token doubles as X-Tableau-Auth for Metadata/VDS."""
    body = {"credentials": {
        "personalAccessTokenName": creds.pat_name,
        "personalAccessTokenSecret": creds.secret,
        "site": {"contentUrl": content_url or ""},
    }}
    resp = client.post("/api/%s/auth/signin" % version, json=body)
    if resp.status_code != 200:
        # Do not include the response body verbatim; it can echo the request.
        raise AuthError("sign-in failed (HTTP %d) at /api/%s/auth/signin"
                        % (resp.status_code, version))
    try:
        creds_out = resp.json()["credentials"]
    except (ValueError, KeyError):
        raise AuthError("sign-in returned an unexpected body shape")
    site = creds_out.get("site", {})
    user = creds_out.get("user", {})
    token = creds_out.get("token")
    if not token:
        raise AuthError("sign-in returned no token")
    return {
        "token": token,
        "site_id": site.get("id"),
        "site_content_url": site.get("contentUrl", content_url or ""),
        "site_name": site.get("name") or site.get("contentUrl") or content_url or "Default",
        "user_id": user.get("id"),
    }


def signout(client, version, token):
    # type: (httpx.Client, str, str) -> bool
    """POST /api/{version}/auth/signout. Best-effort and idempotent -- returns
    True on a clean 204, False otherwise, and never raises."""
    if not token:
        return False
    try:
        resp = client.post("/api/%s/auth/signout" % version,
                           headers={"X-Tableau-Auth": token})
    except httpx.HTTPError:
        return False
    return resp.status_code in (200, 204)
