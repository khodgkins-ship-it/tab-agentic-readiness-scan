"""Live-run configuration: load, validate, and guard.

There was no config file in the prototype -- the CLI took only `--fixture/--out`.
A live run needs to know the host, the site, and the deployment type; the
credential *secret* is deliberately NOT part of this (it comes from the
environment or the OS keychain). `load_config` reads YAML or JSON by extension;
`assert_no_secrets_in_config` (in `security.py`) is run by the CLI on the loaded
dict *before any client is constructed*.

Example config (YAML)::

    host: https://10ax.online.tableau.com   # or https://tableau.mycorp.com
    site_content_url: ""                     # "" = the default site
    deployment_type: cloud                   # cloud | server
    pat_name: estate-scan-readonly           # NON-secret; secret via env/keychain
    # api_version: "3.24"                     # optional pin; else negotiated
    core_metrics: [Revenue, Active Customers]
    domains: []
    timeout_seconds: 60
    session_refresh_seconds: 3000
    permissions_sample: 50                   # content objects sampled per type
"""

import json
import os

__all__ = ["ConfigError", "load_config", "validate_config"]

_VALID_DEPLOYMENTS = frozenset({"cloud", "server"})


class ConfigError(Exception):
    """The config file is missing, unparseable, or invalid."""


def load_config(path):
    # type: (str) -> dict
    """Load a live-run config from a YAML or JSON file. Does not resolve secrets
    and does not construct any client."""
    if not os.path.isfile(path):
        raise ConfigError("config file not found: %s" % path)
    with open(path, "r") as fh:
        text = fh.read()
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".yaml", ".yml"):
            import yaml  # pyyaml is a declared dependency
            data = yaml.safe_load(text)
        elif ext == ".json":
            data = json.loads(text)
        else:
            # Try YAML first (a superset of JSON), then JSON, before giving up.
            try:
                import yaml
                data = yaml.safe_load(text)
            except Exception:
                data = json.loads(text)
    except Exception as exc:
        raise ConfigError("could not parse config %s: %s" % (path, exc))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("config %s must be a mapping, got %s"
                          % (path, type(data).__name__))
    return data


def validate_config(config):
    # type: (dict) -> dict
    """Validate a loaded config and return it. Raises `ConfigError` on a problem.

    Secret hygiene is enforced separately (security.assert_no_secrets_in_config);
    this checks the *shape* the live client needs."""
    host = config.get("host")
    if not host or not isinstance(host, str):
        raise ConfigError("config requires a non-empty string 'host' "
                          "(the Tableau base URL, e.g. https://10ax.online.tableau.com)")
    if not host.startswith(("http://", "https://")):
        raise ConfigError("config 'host' must include a scheme (https://...)")
    deployment = config.get("deployment_type", "cloud")
    if deployment not in _VALID_DEPLOYMENTS:
        raise ConfigError("config 'deployment_type' must be one of %s, got %r"
                          % (", ".join(sorted(_VALID_DEPLOYMENTS)), deployment))
    scu = config.get("site_content_url", "")
    if not isinstance(scu, str):
        raise ConfigError("config 'site_content_url' must be a string "
                          "(\"\" for the default site)")
    if "permissions_sample" in config:
        ps = config["permissions_sample"]
        # bool is an int subclass -- reject it explicitly so `true`/`false`
        # cannot masquerade as a sample size.
        if isinstance(ps, bool) or not isinstance(ps, int) or ps < 0:
            raise ConfigError("config 'permissions_sample' must be a non-negative "
                              "integer (content objects sampled per type)")
    return config
