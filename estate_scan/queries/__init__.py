"""The fixed, versioned query set.

Queries are addressed by name against `manifest.json`, never generated at
runtime (build brief section 6). The manifest records a sha256 per query; the
loader verifies it so a query file cannot drift from the recorded version
without the run metadata noticing.
"""

import hashlib
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_MANIFEST_PATH = os.path.join(_HERE, "manifest.json")


def load_manifest():
    # type: () -> dict
    with open(_MANIFEST_PATH, "r") as fh:
        return json.load(fh)


def query_set_version():
    # type: () -> str
    return load_manifest()["query_set_version"]


def _sha256(path):
    # type: (str) -> str
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_query(name, verify=True):
    # type: (str, bool) -> str
    """Return the GraphQL text for a named query, verifying its checksum.

    Raises KeyError for an unknown name and ValueError on a checksum mismatch,
    which means a .graphql file was edited without regenerating the manifest.
    """
    manifest = load_manifest()
    entry = manifest.get("graphql", {}).get(name)
    if entry is None:
        raise KeyError("unknown query: %r (known: %s)" % (
            name, ", ".join(sorted(manifest.get("graphql", {}).keys()))))
    path = os.path.join(_HERE, entry["file"])
    if verify:
        actual = _sha256(path)
        if actual != entry["sha256"]:
            raise ValueError(
                "checksum mismatch for query %r: manifest has %s, file is %s. "
                "Regenerate with `python -m estate_scan.queries.checksum`."
                % (name, entry["sha256"], actual))
    with open(path, "r") as fh:
        return fh.read()


def shard_hint(name):
    # type: (str) -> dict
    return load_manifest()["graphql"][name]["shard"]


def verify_all():
    # type: () -> None
    """Verify every query file against the manifest. Raises on mismatch."""
    manifest = load_manifest()
    for name in manifest.get("graphql", {}):
        load_query(name, verify=True)
