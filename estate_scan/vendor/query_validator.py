"""
query_validator.py — validates generated GraphQL queries against the Tableau
Metadata API schema before sending them to Tableau.

Uses two validation layers:
  1. Comprehensive schema validation (schema_validator.py) - checks field existence,
     interface types, inline fragments
  2. Tableau-specific validation - checks lineage fields, filter arguments,
     totalCount placement, variable issues

Returns a list of error strings. Empty list means the query is valid.

---------------------------------------------------------------------------
VENDORED from tableau/tableau-metadata-explorer (app/proxy/query_validator.py),
Apache License 2.0, Copyright (c) Salesforce, Inc. See vendor/LICENSE and
vendor/NOTICE. We run it over our *fixed, versioned* query set as a build-time
check (queries/__init__.py), the reuse this repo was written for.

MODIFICATIONS (marked per Apache 2.0 §4b):
  * imports rebased from the upstream `proxy` package to `estate_scan.vendor`;
  * the comprehensive layer (schema_validator + the 6.9 MB introspection dump)
    and the per-tenant runtime rules are intentionally not vendored, so both
    optional imports resolve absent and the module runs its self-contained
    structural checks plus the types-and-filters.md whitelist. This is the same
    graceful degradation the upstream try/except already provides.
Otherwise the validation logic is unmodified.
---------------------------------------------------------------------------
"""

import re
from estate_scan.vendor import schema_loader

try:
    from estate_scan.vendor import query_rules
    _RUNTIME_RULES = True
except ImportError:
    _RUNTIME_RULES = False

try:
    from estate_scan.vendor import schema_validator
    _COMPREHENSIVE_VALIDATION = True
except ImportError:
    _COMPREHENSIVE_VALIDATION = False

# ── Lineage whitelist built from schema ───────────────────────────────────────
# Populated at startup from the types-and-filters.md file.
# Maps type name → set of valid upstream/downstream field names (both direct
# and *Connection paginated forms).

_lineage_whitelist: dict = {}   # {"Workbook": {"downstreamMetrics", "downstreamMetricsConnection", ...}}
_filter_whitelist:  dict = {}   # {"workbooksConnection": {"luid", "luidWithin", ...}}
_built = False


def _build_whitelists():
    global _lineage_whitelist, _filter_whitelist, _built
    if _built:
        return

    content = schema_loader._types_and_filters
    if not content:
        return

    # ── Parse lineage lines ───────────────────────────────────────────────────
    # Pattern: "  # upstream: foo, bar" or "  # downstream: foo, bar"
    lineage_pattern = re.compile(
        r'### (\w+).*?(?=### |\Z)',
        re.DOTALL
    )
    for match in lineage_pattern.finditer(content):
        type_name = match.group(1)
        block = match.group(0)
        valid_fields = set()

        for direction in ('upstream', 'downstream', 'referencedBy'):
            line_match = re.search(rf'# {direction}: (.+)', block)
            if line_match:
                fields = [f.strip() for f in line_match.group(1).split(',')]
                for field in fields:
                    if field:
                        valid_fields.add(field)
                        # Also add the *Connection paginated form
                        valid_fields.add(field + 'Connection')

        if valid_fields:
            _lineage_whitelist[type_name] = valid_fields

    # ── Parse filter whitelists ───────────────────────────────────────────────
    filter_pattern = re.compile(r'### (\w+_Filter)\n(.*?)(?=\n### |\Z)', re.DOTALL)
    for match in filter_pattern.finditer(content):
        filter_name = match.group(1)
        # Extract field names (lines starting with spaces then a word char)
        fields = re.findall(r'^\s+(\w+):', match.group(2), re.MULTILINE)
        if fields:
            # Map from connection name to filter fields
            # e.g. Workbook_Filter → workbooksConnection
            type_name = filter_name.replace('_Filter', '')
            conn_name = type_name[0].lower() + type_name[1:] + 'sConnection'
            _filter_whitelist[conn_name] = set(fields)
            # Also store by filter type name directly
            _filter_whitelist[filter_name] = set(fields)

    _built = True


# ── Validation ────────────────────────────────────────────────────────────────

def _extract_fields_used(query: str) -> list:
    """
    Extract lineage field names used in the query.
    Only returns top-level field names — skips fields used inside
    inline fragments (... on TypeName { }) to avoid false positives
    where a field like upstreamColumns is valid on a nested type
    (e.g. ColumnField) but not on the outer connection type.
    """
    # Strip inline fragments (... on TypeName { ... }) before scanning.
    # upstreamColumns inside "... on ColumnField { }" is valid on ColumnField
    # but must not be attributed to the outer connection type.
    # We strip them by removing lines that are inside a "... on X {" block.
    lines = query.split("\n")
    cleaned_lines = []
    skip_depth = 0
    for line in lines:
        stripped = line.strip()
        if re.match(r"\.\.\.\s+on\s+\w+", stripped):
            skip_depth += stripped.count("{") - stripped.count("}")
            continue
        if skip_depth > 0:
            skip_depth += stripped.count("{") - stripped.count("}")
            if skip_depth < 0:
                skip_depth = 0
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    fields = re.findall(r'\b(downstream\w+|upstream\w+|referencedBy\w+)\b', cleaned)
    return fields


def _get_type_from_context(query: str, field: str) -> str:
    """
    Try to infer which type a lineage field is being used on by looking
    at what connection is open when the field appears.
    """
    # Look for patterns like:
    # workbooksConnection { ... downstreamMetricDefinitionsConnection
    # publishedDatasourcesConnection { ... downstreamMetricDefinitionsConnection
    connection_map = {
        'workbooksConnection':            'Workbook',
        'publishedDatasourcesConnection': 'PublishedDatasource',
        'databaseTablesConnection':       'DatabaseTable',
        'customSQLTablesConnection':      'CustomSQLTable',
        'sheetsConnection':               'Sheet',
        'dashboardsConnection':           'Dashboard',
        'flowsConnection':                'Flow',
        'embeddedDatasourcesConnection':  'EmbeddedDatasource',
    }

    # Find position of the field in the query
    pos = query.find(field)
    if pos == -1:
        return None

    # Look backwards for the nearest connection name
    preceding = query[:pos]
    for conn, type_name in connection_map.items():
        if conn in preceding:
            # Find the last occurrence before our field
            last_pos = preceding.rfind(conn)
            if last_pos != -1:
                return type_name

    return None


def validate(query: str) -> list:
    """
    Validate a GraphQL query against the schema.
    Returns a list of error strings. Empty = valid.
    """
    if not schema_loader._loaded:
        schema_loader.load()
    _build_whitelists()

    errors = []

    # ── Comprehensive schema validation (field existence, interfaces) ───────────
    if _COMPREHENSIVE_VALIDATION:
        try:
            schema_errors = schema_validator.validate_query(query)
            errors.extend(schema_errors)
        except Exception:
            # Fall back to legacy validation if comprehensive validation fails
            pass

    # ── Check 1: Invalid lineage fields ──────────────────────────────────────
    lineage_fields = _extract_fields_used(query)
    for field in set(lineage_fields):
        # Remove 'Connection' suffix to get the base name for lookup
        base = field[:-len('Connection')] if field.endswith('Connection') else field
        type_name = _get_type_from_context(query, field)

        if type_name and type_name in _lineage_whitelist:
            valid = _lineage_whitelist[type_name]
            if field not in valid and base not in valid:
                errors.append(
                    f"'{field}' is not a valid field on {type_name}. "
                    f"Valid lineage fields for {type_name}: "
                    + ', '.join(sorted(f for f in valid if not f.endswith('Connection')))
                )

    # ── Check 2: totalCount inside pageInfo ───────────────────────────────────
    # Pattern: pageInfo { ... totalCount ... }
    page_info_blocks = re.findall(r'pageInfo\s*\{([^}]+)\}', query)
    for block in page_info_blocks:
        if 'totalCount' in block:
            errors.append(
                "'totalCount' must not be inside pageInfo { }. "
                "Place it as a sibling: pageInfo { hasNextPage endCursor }\\ntotalCount"
            )
            break

    # ── Check 3: Variable declared with ! and default value ───────────────────
    bad_vars = re.findall(r'\(\s*\$\w+\s*:\s*\w+!\s*=\s*\S+', query)
    for var in bad_vars:
        errors.append(
            f"Invalid variable declaration '{var.strip()}': "
            "a non-null type (!) cannot have a default value. "
            "Either remove '!' or remove the default."
        )

    # ── Check 4: unused variables ────────────────────────────────────────────
    # A variable declared in the signature but never used in the body causes
    # an UnusedVariable validation error from Tableau.
    declared = re.findall(r'\$(\w+)\s*:', query)
    for var in declared:
        occurrences = len(re.findall(r'\$' + re.escape(var) + r'\b', query))
        if occurrences < 2:  # 1 = only in signature, needs ≥2 to be used in body
            errors.append(
                f"Variable '${var}' is declared but never used in the query body. "
                f"Either use it (e.g. first: ${var}) or remove it from the signature."
            )

    # ── Check 6: Schema-driven filter validation ────────────────────────────────
    # For every connectionFoo(...filter: {field: val}) in the query, check that
    # every field used in the filter is in the whitelist built from types-and-filters.md.
    # This covers ALL connection types automatically — no per-type rules needed.
    _build_whitelists()

    # Specific guidance for known cases where the correct approach is different
    _FILTER_GUIDANCE = {
        ('workbooksConnection', 'owner'):             ' Use REST GET /users/{ownerLuid}/workbooks then GraphQL luidWithin.',
        ('workbooksConnection', 'ownerEmail'):        ' Use REST GET /users/{ownerLuid}/workbooks then GraphQL luidWithin.',
        ('workbooksConnection', 'ownerLuid'):         ' Use REST GET /users/{ownerLuid}/workbooks then GraphQL luidWithin.',
        ('workbooksConnection', 'ownerLuidWithin'):   ' Use REST GET /users/{ownerLuid}/workbooks then GraphQL luidWithin.',
        ('customSQLTablesConnection', 'connectionType'): ' Fetch all custom SQL tables without a filter; inspect connectionType on each result node instead.',
    }

    # Match: someConnection(...filter: { field1: val, field2: val ... })
    # [^{}]* stops at nested braces so we don't cross into the selection set
    filter_pattern = re.compile(
        r'(\w+Connection)\s*\([^)]*?filter\s*:\s*\{([^{}]*?)\}',
        re.DOTALL
    )
    for fm in filter_pattern.finditer(query):
        conn_name = fm.group(1)
        filter_body = fm.group(2)
        allowed = _filter_whitelist.get(conn_name)
        if not allowed:
            continue  # no whitelist for this connection — skip
        used_fields = re.findall(r'\b([a-zA-Z_]\w*)\s*:', filter_body)
        for field in used_fields:
            if field not in allowed:
                guidance = _FILTER_GUIDANCE.get((conn_name, field), '')
                errors.append(
                    "Invalid filter field '{}' on {}. Allowed filter fields: {}.{}".format(
                        field, conn_name, ', '.join(sorted(allowed)), guidance
                    )
                )

    # ── Check 5: permissionMode on nested connections ─────────────────────────
    # Find all uses of permissionMode and check they're on root connections
    perm_matches = list(re.finditer(r'(\w+)\s*\([^)]*permissionMode', query))
    root_connections = {
        'workbooksConnection', 'publishedDatasourcesConnection',
        'databaseTablesConnection', 'customSQLTablesConnection',
        'sheetsConnection', 'dashboardsConnection', 'flowsConnection',
        'databasesConnection', 'embeddedDatasourcesConnection',
        'columnFieldsConnection', 'calculatedFieldsConnection',
    }
    for match in perm_matches:
        conn = match.group(1)
        if conn not in root_connections:
            errors.append(
                f"'permissionMode' is only valid on root connections, not on '{conn}'."
            )

    # ── Check 7: Runtime-extensible semantic rules ────────────────────────────
    # Data-driven rules (defaults JSON + per-tenant DB rows) that catch
    # schema-VALID but semantically WRONG queries the structural checks above
    # cannot — e.g. datasource IDs into a field connection's idWithin. `block`
    # rules join the error list (and drive the one-shot fix loop); `warn` rules
    # are advisory and surfaced via validate_with_warnings(), not returned here.
    if _RUNTIME_RULES:
        try:
            for hit in query_rules.apply(query):
                if hit.get('severity') == 'block':
                    errors.append(hit['message'])
        except Exception:
            pass  # a broken rule store must never break validation

    return errors


def validate_with_warnings(query: str) -> tuple:
    """
    Like validate(), but also returns advisory (warn-severity) rule hits so the
    caller can surface them without treating them as blocking fix-loop errors.
    Returns (errors, warnings) — both lists of strings. errors == validate().
    """
    errors = validate(query)
    warnings = []
    if _RUNTIME_RULES:
        try:
            warnings = [h['message'] for h in query_rules.apply(query)
                        if h.get('severity') == 'warn']
        except Exception:
            pass
    return errors, warnings


def format_errors_for_claude(query: str, errors: list) -> str:
    """
    Format validation errors into a clear prompt for Claude to fix the query.
    """
    error_list = '\n'.join(f'- {e}' for e in errors)
    return (
        f"The following GraphQL query has schema validation errors that will cause "
        f"Tableau to reject it. Fix ONLY the listed errors. Do not change anything else.\n\n"
        f"ERRORS:\n{error_list}\n\n"
        f"QUERY TO FIX:\n{query}\n\n"
        f"Return only the corrected GraphQL query, no explanation, no markdown fences."
    )
