"""Read-only enforcement primitives (pure; no httpx, no network).

Read-only-against-Tableau is a security invariant the spec demands be enforced
*in code, not by convention* (build brief section 6; 03 section 1). This module
holds the deterministic, transport-free checks so they can be unit-tested with
no client and reused by every gate:

  * Gate A (by-name GraphQL): the fixed query set is verified to contain only
    `query` operations -- never `mutation`/`subscription`. See
    `assert_graphql_read_only`, called from `queries.assert_read_only`.
  * Gate C (transport): the httpx guard in `security.py` re-parses each outbound
    body and refuses a GraphQL mutation or a VizQL Data Service write, using the
    same functions here. Two placements, one implementation.

Keeping this module dependency-free (stdlib `re`/`json` only) means importing the
offline pipeline never drags in httpx, and the checks are trivially testable.
"""

import re

__all__ = [
    "ReadOnlyViolation",
    "graphql_operations",
    "assert_graphql_read_only",
    "assert_vds_body_read_only",
]


class ReadOnlyViolation(Exception):
    """A would-be write reached a read-only surface.

    Raised hard and never caught-and-continued: a mutation must abort the run,
    not be logged and skipped. Messages name the offending operation/resource
    but never echo a secret.
    """


# -- GraphQL operation parsing ----------------------------------------------
# We control the fixed query set, so a lightweight tokenizer is enough: strip
# comments and string literals (so a word like "mutation" inside a description
# cannot trip the check), then find operation-definition keywords.

_LINE_COMMENT = re.compile(r"#[^\n\r]*")
_BLOCK_STRING = re.compile(r'"""(?:.|\n)*?"""')
_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
# A keyword only counts as an operation definition when it is followed by an
# operation name, a variable-definition list `(`, or a selection set `{` --
# never when it is a field named e.g. `query`.
_OP = re.compile(r"\b(query|mutation|subscription)\b\s*(?=[A-Za-z_(@{])")


def _strip(text):
    # type: (str) -> str
    text = _LINE_COMMENT.sub("", text)
    text = _BLOCK_STRING.sub('""', text)
    text = _STRING.sub('""', text)
    return text


def graphql_operations(text):
    # type: (str) -> list
    """Return the operation keywords (`query`/`mutation`/`subscription`) that a
    GraphQL document defines, in order.

    Anonymous query shorthand (`{ ... }` with no keyword) reports as a single
    ``["query"]`` -- it is a read. An empty/garbage document reports ``[]``.
    """
    stripped = _strip(text)
    ops = _OP.findall(stripped)
    if ops:
        return ops
    # No keyword: anonymous shorthand `{...}` is a query; anything else unknown.
    return ["query"] if "{" in stripped else []


def assert_graphql_read_only(text, label=""):
    # type: (str, str) -> None
    """Raise `ReadOnlyViolation` unless every operation in `text` is a `query`.

    An empty/unparseable document is refused too -- fail closed, never open.
    """
    ops = graphql_operations(text)
    where = (" in %s" % label) if label else ""
    if not ops:
        raise ReadOnlyViolation(
            "no readable GraphQL query operation found%s (fail-closed)" % where)
    bad = sorted({o for o in ops if o != "query"})
    if bad:
        raise ReadOnlyViolation(
            "refusing non-read GraphQL operation%s: %s" % (where, ", ".join(bad)))


# -- VizQL Data Service body parsing ----------------------------------------
# VDS is read-only *by construction*: the only endpoint we ever POST to is
# query-datasource, and its body may carry only a datasource reference plus a
# read query (fields/filters). Any other top-level key -- or a write-shaped verb
# in the query -- is refused, so there is no publish/update surface even if a
# caller hand-builds a body.

_VDS_ALLOWED_TOP = frozenset({"datasource", "query", "options"})
_VDS_ALLOWED_QUERY = frozenset({"fields", "filters"})


def assert_vds_body_read_only(body, label="vds"):
    # type: (dict, str) -> None
    """Raise `ReadOnlyViolation` unless a VDS body carries only read keys."""
    if not isinstance(body, dict):
        raise ReadOnlyViolation("%s body is not an object (fail-closed)" % label)
    extra = sorted(set(body) - _VDS_ALLOWED_TOP)
    if extra:
        raise ReadOnlyViolation(
            "refusing VDS body with non-read key(s) in %s: %s"
            % (label, ", ".join(extra)))
    query = body.get("query")
    if query is not None:
        if not isinstance(query, dict):
            raise ReadOnlyViolation("%s query is not an object (fail-closed)" % label)
        q_extra = sorted(set(query) - _VDS_ALLOWED_QUERY)
        if q_extra:
            raise ReadOnlyViolation(
                "refusing VDS query with non-read key(s) in %s: %s"
                % (label, ", ".join(q_extra)))
