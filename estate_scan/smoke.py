"""R6: the guarded live-smoke path -- a read-only connectivity self-test.

This is the thing you run *first* against a real customer site: it confirms the
PAT, the permissions, and the whole read path work end to end -- version
negotiation, sign-in, capability detection, the Metadata extraction (with
partial-response subdivision), and a clean sign-out -- WITHOUT persisting an
estate or emitting a report.

It is deliberately not a new pipeline. `run_smoke` drives the *production*
`ExtractRunner` over the *production* `LiveClient`, so every read-only gate
(Gate A by-name GraphQL, Gate B GET-only REST registry, Gate C transport guard)
and the partial-response subdivision apply exactly as in a real scan. The only
differences from `scan --config --live` are that the store is in-memory and
discarded, and nothing customer-facing is written -- the output is a short
liveness summary, not the five artifacts.

Guarded so it can never run by accident and never runs in CI (see `cli.cmd_smoke`):
  * it is a separate command, never part of `scan`/`report`;
  * it refuses to connect without the explicit ``--live`` opt-in;
  * credentials resolve only from the environment / OS keychain, so a checkout
    with no ``ESTATE_SCAN_PAT_*`` set (as in CI) can never reach a real site.

`run_smoke` itself is transport-agnostic: the offline test drives it with a
`LiveClient` over `FixtureTransport`, proving read-only end-to-end behaviour and
sign-out with no network and no credentials.
"""

from typing import Optional

from estate_scan.extract.runner import ExtractRunner, new_run_id
from estate_scan.store import Store

# The order capabilities are shown in the summary -- matches
# LiveClient.detect_capabilities so the report reads top-down as the probe runs.
_CAP_ORDER = ("metadata_api", "rest_jobs", "rest_tasks", "admin_insights",
              "repository", "vizql_data_service", "data_quality_api")


def run_smoke(client, store=None):
    # type: (object, Optional[Store]) -> dict
    """Run a read-only extraction self-test against a *connected* `client`.

    Returns a liveness summary dict. Reuses the production `ExtractRunner`, so the
    read-only gates and partial-response subdivision are exercised exactly as in a
    real scan. Nothing is emitted: the default store is in-memory and discarded
    when this returns (a test may pass its own store to inspect it). The runner
    signs out at the end; `run_smoke` also closes in a `finally`, so the session
    is torn down even if the extraction raises partway.
    """
    if not getattr(client, "site_id", None):
        # Match the runner's contract: the caller signs in first (the CLI catches
        # AuthError there). A disconnected client has no site to read.
        raise RuntimeError(
            "run_smoke requires a connected client; call client.connect() first")

    owns_store = store is None
    store = store or Store.open(":memory:")
    # Capture the connection facts before the runner signs out at the end.
    cfg = client.run_config()
    run_id = new_run_id()
    runner = ExtractRunner(client, store, run_id)
    try:
        runner.run()   # extraction + subdivision; signs out at the end
    finally:
        # Belt to the runner's braces: ensure sign-out even if run() raised.
        try:
            client.close()
        except Exception:
            pass

    coverage = {row["measure"]: {"status": row["status"], "reason": row["reason"]}
                for row in store.coverage(run_id)}
    site = cfg.get("site") or {}
    summary = {
        "run_id": run_id,
        "site_id": site.get("id"),
        "site_name": site.get("name"),
        "site_content_url": site.get("contentUrl"),
        "deployment_type": cfg.get("deployment_type"),
        "api_version": cfg.get("api_version"),
        "adoption_source": cfg.get("adoption_source"),
        "credential_source": getattr(client, "credential_source", None),
        "capabilities": dict(getattr(client, "capabilities", None) or {}),
        "coverage": coverage,
        "subdivisions": [
            {"shard": s, "page_size_from": a, "page_size_to": b}
            for (s, a, b) in runner.subdivision_events],
        "signed_out": bool(getattr(client, "is_signed_out", False)),
        "events": list(runner.events),
    }
    if owns_store:
        store.close()
    return summary


# -- rendering ---------------------------------------------------------------

def render_smoke_report(summary, verbose=False):
    # type: (dict, bool) -> str
    """A short, human-readable liveness report. Read-only self-test only -- it
    names the read-only guarantee and that nothing was written to disk."""
    lines = []  # type: list
    a = lines.append

    a("Tableau Estate Scan -- live smoke (read-only connectivity self-test)")
    a("")
    a("  Site:             %s (%s)" % (summary.get("site_name") or "unknown",
                                       summary.get("site_id") or "?"))
    a("  Deployment:       %s" % (summary.get("deployment_type") or "?"))
    a("  API version:      %s (negotiated per host)" % (summary.get("api_version") or "?"))
    a("  Credentials:      %s" % (summary.get("credential_source") or "?"))
    a("  Adoption source:  %s" % (summary.get("adoption_source") or "unavailable"))
    a("")

    caps = summary.get("capabilities") or {}
    a("Capabilities detected")
    # Fixed order first, then any unexpected extras so nothing is hidden.
    seen = set()
    for name in _CAP_ORDER:
        if name in caps:
            seen.add(name)
            a("  %-22s %s" % (name, "yes" if caps[name] else "no"))
    for name in sorted(k for k in caps if k not in seen):
        a("  %-22s %s" % (name, "yes" if caps[name] else "no"))
    a("")

    a("Read (read-only) -- nothing persisted, no report emitted")
    coverage = summary.get("coverage") or {}
    for measure in sorted(coverage):
        row = coverage[measure]
        a("  %-22s %-8s %s" % (measure, row.get("status") or "?",
                               row.get("reason") or ""))
    subs = summary.get("subdivisions") or []
    if subs:
        a("")
        a("Partial-response subdivisions (never accepted truncated data)")
        for s in subs:
            a("  %-30s page_size %s -> %s"
              % (s["shard"], s["page_size_from"], s["page_size_to"]))
    a("")

    a("Session")
    a("  signed out:       %s" % ("yes (token released)" if summary.get("signed_out")
                                  else "NO -- check the log"))
    a("")
    a("Read-only enforced in code (Gate A/B/C). This run wrote nothing to disk.")

    if verbose and summary.get("events"):
        a("")
        a("Run log")
        for line in summary["events"]:
            a("  %s" % line)

    return "\n".join(lines)
