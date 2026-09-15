"""R6 acceptance: the guarded live-smoke path runs read-only end to end and
signs out.

All offline (no network, no credentials): `run_smoke` drives the *production*
`LiveClient` over a `FixtureTransport`, so the read-only gates and the
partial-response subdivision are the shipping ones. The transport records every
(method, path), which lets a test prove -- at the wire level -- that the whole
self-test is read-only and that it signs out at the end.

The CLI-layer tests assert the guard: `--config` alone never connects, and a
planted secret aborts before any client is built.
"""

import json
import os

import pytest

from estate_scan.clients.auth import Credentials
from estate_scan.clients.live import LiveClient
from estate_scan.cli import main
from estate_scan.smoke import render_smoke_report, run_smoke

from tests.transport import FixtureTransport

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# POST is allowed only to these paths; everything else must be a GET. This is the
# read-only envelope the three gates promise, checked at the transport boundary.
_READ_POST_SUFFIXES = ("/auth/signin", "/auth/signout")
_READ_POST_EXACT = ("/api/metadata/graphql",
                    "/api/v1/vizql-data-service/query-datasource")


def _estate(profile="median"):
    with open(os.path.join(FIXTURES, profile, "estate.json")) as fh:
        return json.load(fh)


def _config(estate):
    return {"host": "https://fixture.online.tableau.com",
            "deployment_type": estate.get("meta", {}).get("deployment_type", "cloud"),
            "site_content_url": ""}


def _connected(estate=None, **transport_kwargs):
    """A production LiveClient over a FixtureTransport, signed in but with
    capabilities NOT yet detected -- run_smoke drives detection via the runner,
    exactly as the CLI path does."""
    estate = estate or _estate()
    ft = FixtureTransport(estate, **transport_kwargs)
    client = LiveClient(_config(estate), transport=ft.transport,
                        credentials=Credentials("pat", "secret", "env"))
    client.connect()
    return client, ft


def _write(path, obj):
    with open(path, "w") as fh:
        json.dump(obj, fh)
    return path


# -- run_smoke: read-only end to end, and signs out -------------------------

def test_smoke_runs_read_only_end_to_end_and_signs_out():
    client, ft = _connected()
    summary = run_smoke(client)

    # It signed in and it signed out (the acceptance bar), both as POSTs the
    # transport saw. The version was negotiated (3.24), so the paths are versioned.
    assert ("POST", "/api/%s/auth/signin" % ft.api_version) in ft.requests
    assert ("POST", "/api/%s/auth/signout" % ft.api_version) in ft.requests
    assert summary["signed_out"] is True

    # Every write-capable verb the transport saw was a read: a POST only to the
    # sign-in/out, Metadata GraphQL, or VDS query paths; everything else a GET.
    for method, path in ft.requests:
        if method == "POST":
            ok = (path in _READ_POST_EXACT
                  or any(path.endswith(s) for s in _READ_POST_SUFFIXES))
            assert ok, "unexpected POST to %s -- not a read path" % path
        else:
            assert method == "GET", "unexpected %s to %s" % (method, path)

    # The read actually happened end to end: the Metadata surface was queried and
    # the object measures came back measured, not skipped.
    assert ("POST", "/api/metadata/graphql") in ft.requests
    assert summary["capabilities"]["metadata_api"] is True
    assert summary["coverage"]["projects"]["status"] == "ok"
    assert summary["coverage"]["workbooks"]["status"] == "ok"


def test_smoke_report_renders_the_liveness_summary():
    client, _ft = _connected()
    text = render_smoke_report(run_smoke(client))
    assert "read-only" in text
    assert "signed out:" in text
    assert "yes (token released)" in text
    # It names the site and the negotiated version -- the connection facts.
    assert "Capabilities detected" in text
    assert "wrote nothing to disk" in text


def test_smoke_subdivides_on_a_partial_response():
    # A node-limit partial on the workbooks page must subdivide through the live
    # path exactly as in a real scan (never accept truncated data).
    client, _ft = _connected(partial_over={"workbooks": 50})
    summary = run_smoke(client)
    wb = [s for s in summary["subdivisions"] if s["shard"] == "workbooks"]
    assert wb, "expected the workbooks shard to subdivide on a partial"
    assert wb[0]["page_size_to"] < wb[0]["page_size_from"]
    # And it still completed -- subdivision recovered the full page.
    assert summary["coverage"]["workbooks"]["status"] == "ok"


def test_smoke_aborts_but_still_signs_out_when_metadata_disabled():
    # The one capability with no substitute. detect_capabilities (inside the
    # runner) hard-aborts naming the tsm fix -- but the session must still be torn
    # down, so a signout POST is issued despite the abort.
    client, ft = _connected(metadata_available=False)
    with pytest.raises(SystemExit) as exc:
        run_smoke(client)
    assert "Metadata API" in str(exc.value)
    assert ("POST", "/api/%s/auth/signout" % ft.api_version) in ft.requests
    assert client.is_signed_out is True


def test_run_smoke_requires_a_connected_client():
    estate = _estate()
    ft = FixtureTransport(estate)
    client = LiveClient(_config(estate), transport=ft.transport,
                        credentials=Credentials("pat", "secret", "env"))
    # Not connected: no site_id, so run_smoke refuses rather than reading nothing.
    with pytest.raises(RuntimeError):
        run_smoke(client)
    assert ("POST", "/api/%s/auth/signin" % ft.api_version) not in ft.requests


# -- CLI guard: off by default, never in CI ----------------------------------

def test_smoke_config_dry_run_validates_without_connecting(tmp_path, capsys):
    cfg = _write(str(tmp_path / "live.json"),
                 {"host": "https://x.online.tableau.com",
                  "deployment_type": "cloud", "site_content_url": "",
                  "pat_name": "estate-scan-readonly"})
    rc = main(["smoke", "--config", cfg])
    assert rc == 0
    out = capsys.readouterr().out
    assert "is valid" in out
    assert "Re-run with --live" in out


def test_smoke_config_with_planted_secret_aborts(tmp_path):
    cfg = _write(str(tmp_path / "live.json"),
                 {"host": "https://x.online.tableau.com",
                  "deployment_type": "cloud",
                  "pat_secret": "AbcdEFGH1234ijklMNOP5678qrstUVWXyz90ABcd"})
    with pytest.raises(SystemExit) as exc:
        main(["smoke", "--config", cfg, "--live"])
    # Aborts before connecting and never echoes the secret value.
    assert "AbcdEFGH1234ijklMNOP5678qrstUVWXyz90ABcd" not in str(exc.value)
