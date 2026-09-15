"""R1: the CLI live branch -- secret hygiene and the two-step live opt-in.

These assert the CLI-layer contract only (config validation, the secret abort,
and the `--live`/`--config` coupling); the live client's behaviour itself is
covered offline in `test_live.py`. No network is touched here.
"""

import json
import os

import pytest

from estate_scan.cli import main


def _write(path, obj):
    with open(path, "w") as fh:
        json.dump(obj, fh)
    return path


def test_config_dry_run_validates_without_connecting(tmp_path, capsys):
    cfg = _write(str(tmp_path / "live.json"),
                 {"host": "https://x.online.tableau.com",
                  "deployment_type": "cloud", "site_content_url": "",
                  "pat_name": "estate-scan-readonly"})
    rc = main(["scan", "--config", cfg, "--out", str(tmp_path / "out")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "is valid" in out
    # A dry run must not create a store (it never connected or extracted).
    assert not os.path.exists(str(tmp_path / "out" / "estate.db"))


def test_config_with_planted_secret_aborts(tmp_path):
    cfg = _write(str(tmp_path / "live.json"),
                 {"host": "https://x.online.tableau.com",
                  "deployment_type": "cloud",
                  "pat_secret": "AbcdEFGH1234ijklMNOP5678qrstUVWXyz90ABcd"})
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--config", cfg, "--out", str(tmp_path / "out")])
    # Aborts and never echoes the secret value.
    assert "pat_secret" not in str(exc.value) or "AbcdEFGH" not in str(exc.value)
    assert "AbcdEFGH1234ijklMNOP5678qrstUVWXyz90ABcd" not in str(exc.value)


def test_invalid_config_shape_reports_config_error(tmp_path):
    # Missing host: validate_config raises ConfigError, which propagates.
    from estate_scan.config import ConfigError
    cfg = _write(str(tmp_path / "live.json"), {"deployment_type": "cloud"})
    with pytest.raises(ConfigError):
        main(["scan", "--config", cfg, "--out", str(tmp_path / "out")])


def test_live_without_config_is_refused(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--fixture", "tests/fixtures/median", "--live",
              "--out", str(tmp_path / "out")])
    assert "requires --config" in str(exc.value)


def test_fixture_and_config_are_mutually_exclusive(tmp_path):
    cfg = _write(str(tmp_path / "live.json"), {"host": "https://x"})
    # argparse enforces the mutually-exclusive group -> SystemExit(2).
    with pytest.raises(SystemExit):
        main(["scan", "--fixture", "f", "--config", cfg,
              "--out", str(tmp_path / "out")])
