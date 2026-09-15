# Contribution 2 — Server support in the client layer

**Upstream:** `tableau/tableau-metadata-explorer`
**Files:** `app/proxy/tableau_rest.py`, `app/proxy/admin_insights.py`, `app/proxy/constants.py`
**Kind:** portability fix — make the client usable against Tableau Server, not just Cloud
**Status:** prepared, **not opened**

---

## Problem (verified against source at R0)

Tableau Server is **not supported end to end**, but the Cloud assumptions are in
the *version* and *usage* layers, not the host layer — a nuance our earlier flat
"Cloud assumptions baked in" note missed:

- **The API version is pinned.** `tableau_rest.py` hardcodes
  `API_VERSION = "3.28"` with **no** `/api/serverinfo` negotiation. Tableau
  Server sites commonly run older REST API versions than Cloud, so a request
  pinned at `3.28` simply fails against them.
- **Usage/governance is Cloud-only with no fallback.** `admin_insights.py`
  sources usage from the Admin Insights datasources (`TS Users`, `Site Content`,
  `TS Events`) over VDS. Admin Insights is a **Cloud** feature; on Server it does
  not exist, and there is no repository-based substitute — the code just yields
  nothing.
- **But the host layer already contemplates Server.** `host_validator.py`
  supports an allowlist for on-prem hostnames and an explicit
  on-box-Server-over-loopback path, so *addressing* a Server is not blocked. The
  gap is downstream of the host.

The consequence for a Server operator: either outright request failures (version)
or, worse, a usage-dependent analysis that returns empty and *reads as a clean
estate* when in fact it was never measured.

## Proposed change

Treat Cloud vs Server as a **recorded attribute plus capability gates**, not a
subclass split:

1. **Negotiate the API version.** On sign-in, `GET /api/serverinfo`, read
   `serverInfo.restApiVersion`, and use it for every subsequent call. Fall back
   to a conservative bootstrap version only if the endpoint is unreachable —
   never guess *high*.
2. **Capability-gate the Cloud-only usage source.** Detect whether Admin Insights
   is present; when it is not (Server), record the usage/adoption dimension as
   `unavailable` with a reason rather than returning empty silently. Where a
   repository-based source is available on Server, use it and record the source.
3. **Name the one hard stop.** If the Metadata API is disabled on the Server (a
   site setting, with no substitute), abort with a message that names the setting
   to enable — rather than degrading into an empty result.

## Illustrative diff (not apply-ready — see README)

`app/proxy/tableau_rest.py` — negotiate instead of pinning:

```diff
-API_VERSION = "3.28"
+# Bootstrap version used only to reach /api/serverinfo; the real version is
+# negotiated per host. Server sites often run older versions than Cloud, so a
+# pinned version breaks against them.
+BOOTSTRAP_API_VERSION = "3.24"
@@
 class TableauRest:
     def signin(self, ...):
+        self.api_version = self._negotiate_version()
         resp = self.call(
-            f"/api/{API_VERSION}/auth/signin", ...
+            f"/api/{self.api_version}/auth/signin", ...
         )
+
+    def _negotiate_version(self):
+        try:
+            r = self.session.get(f"{self.base_url}/api/serverinfo")
+            if r.status_code == 200:
+                return r.json().get("serverInfo", {}).get(
+                    "restApiVersion", BOOTSTRAP_API_VERSION)
+        except RequestException:
+            pass
+        return BOOTSTRAP_API_VERSION
```

`app/proxy/admin_insights.py` — degrade explicitly on Server instead of returning empty:

```diff
 def usage_by_content(self, ...):
     if not self._admin_insights_available():
-        return []
+        # Admin Insights is Cloud-only. On Server, say so — an empty list here
+        # would read as "no usage", i.e. a clean estate, when it was never
+        # measured. Callers record this as unavailable, not clean.
+        return Unavailable(reason="Admin Insights not present (Tableau Server)")
     ...
```

## Test that proves it

- **Version negotiation:** mock `/api/serverinfo` to advertise an older version
  (e.g. `3.19`); assert sign-in and subsequent calls use it, not `3.28`. Mock the
  endpoint unreachable; assert the conservative bootstrap fallback, and that it
  does not guess high.
- **Server usage degradation:** mock a host with no Admin Insights; assert the
  usage path returns an explicit `unavailable` (with reason), never an empty
  success.

## How this repo already embodies the fix (reference for reviewers)

- **Version negotiation:** `estate_scan/clients/auth.py::negotiate_version`
  (`auth.py:133`) does exactly `GET /api/serverinfo` → `restApiVersion`, with
  `BOOTSTRAP_API_VERSION = "3.24"` (`auth.py:45`) used only to reach that
  endpoint and as a conservative fallback. The docstring calls out that this is
  the fix for upstream's pinned `3.28`.
- **Deployment as an attribute, not a subclass:** `EstateClient.deployment_type`
  (`base.py:124`) is a recorded field; one sign-in shape serves both (`auth.py`),
  differing only in `host`/`contentUrl` config.
- **Capability-gated, coverage-honest degradation:** the extract runner gates the
  usage/adoption source on capability and records `skipped`/`unavailable` with a
  reason (`runner.py:181-210` for adoption depth, `runner.py:213-236` for refresh
  tasks) so an unmeasured Server dimension **never reads as clean** — the
  coverage-first-class invariant. `adoption_source` (`base.py:121`) records where
  usage came from (`admin_insights` | `repository` | `unavailable`).
- **The one hard stop:** Metadata-API-disabled is treated as the single
  capability with no substitute → hard abort naming the setting (R0 §(d) scope
  note; enforced on the live path).
