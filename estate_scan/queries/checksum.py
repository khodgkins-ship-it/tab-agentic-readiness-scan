"""Regenerate the sha256 checksums in queries/manifest.json.

Run after editing any .graphql file:

    python -m estate_scan.queries.checksum

Keeping this a separate explicit step (rather than computing checksums at load)
is deliberate: a query changing is a versioning event that should be a visible
diff in the manifest, not a silent recompute.
"""

import hashlib
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_MANIFEST_PATH = os.path.join(_HERE, "manifest.json")


def main():
    # type: () -> None
    with open(_MANIFEST_PATH, "r") as fh:
        manifest = json.load(fh)
    changed = []
    for name, entry in manifest.get("graphql", {}).items():
        path = os.path.join(_HERE, entry["file"])
        with open(path, "rb") as qf:
            digest = hashlib.sha256(qf.read()).hexdigest()
        if entry.get("sha256") != digest:
            changed.append(name)
        entry["sha256"] = digest
    with open(_MANIFEST_PATH, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    if changed:
        print("updated checksums for: %s" % ", ".join(sorted(changed)))
    else:
        print("all checksums already current")


if __name__ == "__main__":
    main()
