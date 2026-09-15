"""Query integrity: the fixed query set validates against the Tableau Metadata
API schema, and its checksums have not drifted.

This is the reuse the metadata explorer's validator was, per 05 section 7.3,
better suited for than its original runtime use: run it over our *fixed*,
version-controlled queries at build time, so a query that references a field or
filter the schema does not have fails the suite instead of silently degrading a
live customer scan. Our CI is this pytest suite, so wiring it here IS wiring it
into CI.

The vendored validator (estate_scan/vendor/query_validator.py) runs its
self-contained structural checks (totalCount placement, unused variables,
non-null-with-default, permissionMode placement) plus the lineage/filter-field
whitelist built from the introspected types-and-filters.md. The heavier
comprehensive layer (a 6.9 MB introspection dump) is intentionally not vendored;
see vendor/NOTICE.
"""

import pytest

from estate_scan import queries
from estate_scan.vendor import query_validator as qv

_MANIFEST = queries.load_manifest()
_QUERY_NAMES = sorted(_MANIFEST.get("graphql", {}))


@pytest.mark.parametrize("name", _QUERY_NAMES)
def test_fixed_query_validates_against_schema(name):
    """Every query in the manifest passes the vendored validator with no errors.

    A schema-breaking edit (a filter field that does not exist, totalCount in
    the wrong place, an unused variable) fails here at build time.
    """
    text = queries.load_query(name, verify=True)
    errors = qv.validate(text)
    assert errors == [], (
        "query %r failed schema validation:\n  - %s"
        % (name, "\n  - ".join(errors)))


def test_the_query_set_is_not_empty():
    # Guard against the parametrized test vacuously passing on an empty set.
    assert _QUERY_NAMES, "no queries found in the manifest to validate"


def test_validator_actually_catches_a_broken_query():
    """The gate has teeth: a query with a known defect must be rejected.

    Without this, a validator that silently no-ops (e.g. its whitelist source
    went missing) would let every real query pass and the gate would rot into
    always-green. We plant one defect per self-contained check.
    """
    planted = {
        "totalCount inside pageInfo": (
            "query q($first:Int!,$after:String){ workbooksConnection"
            "(first:$first,after:$after){ nodes{id} "
            "pageInfo{ hasNextPage endCursor totalCount } } }"),
        "unused variable": (
            "query q($first:Int!,$after:String,$unused:String){ "
            "workbooksConnection(first:$first,after:$after){ nodes{id} "
            "pageInfo{hasNextPage endCursor} } }"),
        "non-null with default": (
            "query q($first:Int! = 10,$after:String){ "
            "workbooksConnection(first:$first,after:$after){ nodes{id} } }"),
        "invalid filter field": (
            'query q{ workbooksConnection(filter:{owner:"x"}){ nodes{id} } }'),
    }
    for label, query in planted.items():
        assert qv.validate(query), "validator did not catch: %s" % label


def test_filter_whitelist_loaded_from_reference():
    """The types-and-filters.md whitelist actually loaded -- so the filter check
    is doing schema work, not passing because the whitelist was empty."""
    text = ("query q{ workbooksConnection(filter:{nonexistentField:1})"
            "{ nodes{id} } }")
    errors = qv.validate(text)
    assert any("nonexistentField" in e for e in errors)


def test_query_checksums_have_not_drifted():
    """Every .graphql file matches the sha256 recorded in the manifest."""
    queries.verify_all()
