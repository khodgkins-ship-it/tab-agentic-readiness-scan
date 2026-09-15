"""Minimal schema-reference loader for the vendored query validator.

The upstream `query_validator` reads one attribute off its `schema_loader`:
`_types_and_filters`, the text of the introspected `types-and-filters.md` from
which it builds the lineage- and filter-field whitelists. Upstream's loader also
pulls the 6.9 MB introspection dump for the comprehensive layer; we vendor only
the whitelist source, so this shim loads that one file and nothing else.

Kept as a separate module (rather than folded into query_validator) so the
vendored validator's `from ... import schema_loader` stays a one-line rebase of
the upstream import -- see vendor/query_validator.py MODIFICATIONS.
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_TYPES_AND_FILTERS_PATH = os.path.join(_HERE, "types-and-filters.md")

_types_and_filters = ""   # type: str
_loaded = False


def load():
    # type: () -> None
    """Load the types-and-filters reference. Idempotent."""
    global _types_and_filters, _loaded
    if _loaded:
        return
    with open(_TYPES_AND_FILTERS_PATH, "r", encoding="utf-8") as fh:
        _types_and_filters = fh.read()
    _loaded = True
