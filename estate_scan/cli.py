"""Command-line entry point (build brief section 4).

Four subcommands sharing one SQLite store at ``<out>/estate.db``:

    scan       extract -> resolve -> group -> rank -> flags, persist run config
    interview  load specialist responses from YAML into interview_responses
    score      facet scoring and domain rollup against the declared target
    report     emit the five artifacts (built in M7)

Each stage runs against the previous stage's output in the store, so the
pipeline is `scan | interview | score | report` with no in-memory hand-off.
`scan` resolves the run id and `interview`/`score`/`report` pick up the most
recent run in the store, so the common single-run case needs no id plumbing.

`scan` runs in one of two modes against the same downstream pipeline:

  * ``--fixture PATH``  -- offline replay of a recorded estate (never a network).
  * ``--config PATH``   -- a real Tableau site (Cloud or Server) via ``LiveClient``.

The live mode is deliberately two-step. ``--config`` alone loads the file, runs
the secret-hygiene abort (``security.assert_no_secrets_in_config``) *before any
client is constructed*, and validates the shape -- but does not connect.
Connecting requires the explicit ``--live`` opt-in, so pointing ``scan`` at a
config to check it can never silently reach out to a real site. Read-only is
enforced in code by the live client's three gates, and credentials come only
from the environment or the OS keychain, never the config file.
"""

import argparse
import json
import os
import sys
from typing import Optional

from estate_scan.clients.fixture import FixtureClient
from estate_scan.derive.group import assign_groups
from estate_scan.derive.rank import rank_groups
from estate_scan.derive.resolve import resolve_all
from estate_scan.extract.runner import ExtractRunner, new_run_id
from estate_scan.flags.engine import evaluate_flags, log_lines
from estate_scan.score import load_interview, score
from estate_scan.store import Store

DB_NAME = "estate.db"
LOG_NAME = "run.log"


def _db_path(out_dir):
    # type: (str) -> str
    return os.path.join(out_dir, DB_NAME)


def _open_store(out_dir, fresh=False):
    # type: (str, bool) -> Store
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    path = _db_path(out_dir)
    if fresh and os.path.exists(path):
        os.remove(path)
    return Store.open(path)


def _existing_store(out_dir):
    # type: (str) -> Store
    path = _db_path(out_dir)
    if not os.path.exists(path):
        raise SystemExit("no store at %s; run `scan` first" % path)
    return Store.open(path)


def _resolve_run(store):
    # type: (Store) -> str
    run_id = store.latest_run_id()
    if run_id is None:
        raise SystemExit("no run found in store; run `scan` first")
    return run_id


# -- scan --------------------------------------------------------------------

def _fixture_path(path):
    # type: (str) -> str
    """Accept either a fixture directory (containing estate.json) or the JSON
    file directly, so `scan --fixture tests/fixtures/median` works."""
    if os.path.isdir(path):
        return os.path.join(path, "estate.json")
    return path


def _load_live_config(path):
    # type: (str) -> dict
    """Load, secret-scan, and validate a live-run config.

    The secret scan runs BEFORE any client is constructed and hard-aborts
    (`SystemExit`) if a PAT/secret was put in the config instead of the
    environment/keychain -- it names the offending key but never the value.
    """
    from estate_scan.config import load_config, validate_config
    from estate_scan.security import assert_no_secrets_in_config
    config = load_config(path)
    assert_no_secrets_in_config(config)   # hard-abort on a planted secret
    validate_config(config)               # shape the live client needs
    return config


def _scan_client(args):
    # type: (argparse.Namespace) -> object
    """Build the scan client for the selected mode. For `--live`, secret hygiene
    is enforced and the version negotiation + sign-in happen here (the runner
    reads `site_id`/`run_config()` at the top of `run()`)."""
    if args.config:
        from estate_scan.clients.auth import AuthError
        from estate_scan.clients.live import LiveClient
        config = _load_live_config(args.config)
        client = LiveClient(config)
        try:
            client.connect()
        except AuthError as exc:
            client.close()
            raise SystemExit("estate-scan: %s" % exc)
        return client
    return FixtureClient.from_path(_fixture_path(args.fixture))


def cmd_scan(args):
    # type: (argparse.Namespace) -> int
    if args.live and not args.config:
        raise SystemExit("scan: --live applies to a live run; it requires --config")
    if args.config and not args.live:
        # Dry validation only: check the config without connecting anywhere.
        _load_live_config(args.config)
        print("config %s is valid. Re-run with --live to connect and scan."
              % args.config)
        print("  credentials come from ESTATE_SCAN_PAT_NAME / "
              "ESTATE_SCAN_PAT_SECRET or the OS keychain, never the config file.")
        return 0

    store = _open_store(args.out, fresh=True)
    client = _scan_client(args)
    config = client.run_config()
    run_id = new_run_id()

    runner = ExtractRunner(client, store, run_id)
    try:
        runner.run()
        resolve_all(store, run_id)
        assign_groups(store, run_id,
                      core_metrics=config.get("core_metrics") or None,
                      model_pass=False)
        rank_groups(store, run_id)
        summary = evaluate_flags(store, run_id)
        store.set_run_config(run_id, json.dumps(config, sort_keys=True))
        store.commit()
    finally:
        # Sign out at the end of every run (spec: no lingering session). The
        # fixture client's close() is a no-op; the live clients release the PAT
        # session here.
        client.close()

    log_path = os.path.join(args.out, LOG_NAME)
    with open(log_path, "w") as fh:
        for line in runner.events:
            fh.write(line + "\n")
        for line in log_lines(summary):
            fh.write(line + "\n")

    store.close()
    fired = ", ".join(f["flag"] for f in summary["fired"]) or "none"
    print("scan %s complete -> %s" % (run_id, _db_path(args.out)))
    print("  flags fired: %s" % fired)
    print("  run log:     %s" % log_path)
    return 0


# -- interview ---------------------------------------------------------------

def cmd_interview(args):
    # type: (argparse.Namespace) -> int
    store = _existing_store(args.out)
    run_id = _resolve_run(store)
    n = load_interview(store, run_id, args.file)
    store.close()
    print("interview: loaded %d response(s) for run %s" % (n, run_id))
    return 0


# -- score -------------------------------------------------------------------

def cmd_score(args):
    # type: (argparse.Namespace) -> int
    store = _existing_store(args.out)
    run_id = _resolve_run(store)
    config = _run_config(store, run_id)
    if args.no_rollup:
        # Drop declared targets: emit facet scores with no domain rollup. The
        # spec calls for exactly this when no target stage is set.
        config = dict(config)
        config["domains"] = []
    findings = score(store, run_id, config=config)
    store.close()
    _print_findings(findings)
    return 0


def _run_config(store, run_id):
    # type: (Store, str) -> dict
    row = store.run_config(run_id)
    return dict(row) if row else {}


def _print_findings(findings):
    # type: (dict) -> None
    facets = findings.get("facets", [])
    domains = findings.get("domains", [])
    print("score: %d facet(s), %d domain(s)" % (len(facets), len(domains)))
    for f in facets:
        print("  facet %-26s %s  (%s)"
              % (f["id"], f["score"], f.get("confidence", "?")))
    for d in domains:
        binding = ", ".join(d.get("binding_constraints", [])) or "none"
        print("  domain %-18s readiness=%s target=%s gap=%s binding=[%s]"
              % (d["id"], d["readiness"], d.get("target_stage"),
                 d.get("gap"), binding))


# -- report ------------------------------------------------------------------

def cmd_report(args):
    # type: (argparse.Namespace) -> int
    store = _existing_store(args.out)
    run_id = _resolve_run(store)
    try:
        from estate_scan.report.emit import emit_all  # noqa: F401
    except ImportError:
        store.close()
        print("report: emission lands in M7 (estate_scan/report/emit.py).")
        print("        scan/interview/score output is in %s"
              % _db_path(args.out))
        return 0
    paths = emit_all(store, run_id, args.out, build=args.build)  # type: ignore
    store.close()
    print("report: wrote %d artifact(s) to %s" % (len(paths), args.out))
    for p in paths:
        print("  %s" % p)
    return 0


# -- argument parsing --------------------------------------------------------

def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(
        prog="estate_scan",
        description="Tableau estate readiness scan (offline, fixture-driven).")
    sub = parser.add_subparsers(dest="command")

    p_scan = sub.add_parser(
        "scan", help="extract, derive, and flag an estate (fixture or live)")
    src = p_scan.add_mutually_exclusive_group(required=True)
    src.add_argument("--fixture",
                     help="path to a recorded estate.json (offline replay)")
    src.add_argument("--config",
                     help="path to a live-run config (YAML/JSON) for a real "
                          "Tableau Cloud/Server site")
    p_scan.add_argument("--live", action="store_true",
                        help="with --config, actually connect and scan; without "
                             "it, --config only validates the config")
    p_scan.add_argument("--out", required=True,
                        help="output directory (holds estate.db and run.log)")
    p_scan.set_defaults(func=cmd_scan)

    p_int = sub.add_parser(
        "interview", help="load specialist interview responses from YAML")
    p_int.add_argument("--out", required=True, help="output directory")
    p_int.add_argument("--file", required=True,
                       help="path to an interview responses YAML file")
    p_int.set_defaults(func=cmd_interview)

    p_score = sub.add_parser(
        "score", help="facet scoring and domain rollup")
    p_score.add_argument("--out", required=True, help="output directory")
    p_score.add_argument("--no-rollup", action="store_true",
                         help="score facets only; skip the domain rollup")
    p_score.set_defaults(func=cmd_score)

    p_report = sub.add_parser(
        "report", help="emit the report artifacts (M7)")
    p_report.add_argument("--out", required=True, help="output directory")
    p_report.add_argument("--build", choices=["presentation", "working"],
                          default="presentation",
                          help="which redaction build to name in the console")
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv=None):
    # type: (Optional[list]) -> int
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
