-- Estate Scan local store (build spec section 6).
--
-- SQLite, normalized, one row per object, `run_id` on everything so multiple
-- scans of the same site coexist and can be compared. Primary keys are
-- (run_id, id) so re-loading a page during a resume is idempotent
-- (INSERT OR REPLACE overwrites the same row rather than duplicating it).
--
-- `coverage` is not optional: every measure the tool attempts records whether
-- it succeeded, so the report can never present an unmeasured dimension as a
-- clean one.

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    site_id         TEXT,
    site_name       TEXT,
    deployment_type TEXT,
    adoption_source TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    mode            TEXT,
    tool_version    TEXT,
    query_set_version TEXT,
    model_pass      INTEGER DEFAULT 0,   -- concept grouping model pass used?
    coverage_json   TEXT,
    config_json     TEXT   -- specialist-supplied domains, target stages, core metrics
);

CREATE TABLE IF NOT EXISTS projects (
    run_id             TEXT,
    id                 TEXT,
    name               TEXT,
    parent_id          TEXT,
    locked_permissions INTEGER,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS datasources (
    run_id              TEXT,
    id                  TEXT,
    luid                TEXT,
    name                TEXT,
    kind                TEXT,          -- published | embedded
    project_id          TEXT,
    project_name        TEXT,
    owner               TEXT,
    is_certified        INTEGER,
    certification_note  TEXT,
    has_extract         INTEGER,
    field_count         INTEGER,
    upstream_table_count INTEGER,
    created_at          TEXT,
    updated_at          TEXT,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS workbooks (
    run_id           TEXT,
    id               TEXT,
    luid             TEXT,
    name             TEXT,
    project_id       TEXT,
    project_name     TEXT,
    owner            TEXT,
    created_at       TEXT,
    updated_at       TEXT,
    sheet_count      INTEGER,
    embedded_ds_count INTEGER,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS fields (
    run_id        TEXT,
    id            TEXT,
    name          TEXT,
    description   TEXT,
    datasource_id TEXT,
    field_type    TEXT,     -- CalculatedField | ColumnField (the __typename)
    data_type     TEXT,
    role          TEXT,
    formula       TEXT,
    is_calculated INTEGER,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS field_refs (
    run_id              TEXT,
    field_id            TEXT,
    referenced_field_id TEXT,
    PRIMARY KEY (run_id, field_id, referenced_field_id)
);

CREATE TABLE IF NOT EXISTS field_usage (
    run_id      TEXT,
    field_id    TEXT,
    sheet_id    TEXT NOT NULL DEFAULT '',
    workbook_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, field_id, sheet_id, workbook_id)
);

CREATE TABLE IF NOT EXISTS custom_sql (
    run_id           TEXT,
    id               TEXT,
    query            TEXT,
    datasource_id    TEXT,
    char_length      INTEGER,
    has_group_by     INTEGER,
    has_user_function INTEGER,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS lineage (
    run_id          TEXT,
    downstream_type TEXT,
    downstream_id   TEXT,
    upstream_type   TEXT,   -- datasource | table
    upstream_id     TEXT,   -- ds id, or table fullName (physical identity)
    upstream_label  TEXT,
    depth           INTEGER,
    PRIMARY KEY (run_id, downstream_type, downstream_id, upstream_type, upstream_id)
);

CREATE TABLE IF NOT EXISTS permissions (
    run_id       TEXT,
    object_type  TEXT,
    object_id    TEXT,
    grantee_type TEXT,
    grantee_id   TEXT,
    capability   TEXT,
    mode         TEXT,
    sampled      INTEGER,
    PRIMARY KEY (run_id, object_type, object_id, grantee_type, grantee_id, capability)
);

CREATE TABLE IF NOT EXISTS refresh_jobs (
    run_id        TEXT,
    task_id       TEXT,
    datasource_id TEXT,
    scheduled_at  TEXT,
    completed_at  TEXT,
    status        TEXT,
    PRIMARY KEY (run_id, task_id)
);

CREATE TABLE IF NOT EXISTS usage_events (
    run_id               TEXT,
    workbook_id          TEXT,
    workbook_luid        TEXT,
    user_id              TEXT,
    event_date           TEXT,
    event_count          INTEGER,   -- views over the retention window
    last_viewed_days_ago INTEGER,
    PRIMARY KEY (run_id, workbook_id)
);

-- derived (M3/M4/M5) -------------------------------------------------------

CREATE TABLE IF NOT EXISTS resolved_formulas (
    run_id            TEXT,
    field_id          TEXT,
    resolved_formula  TEXT,
    normalized_hash   TEXT,
    resolution_depth  INTEGER,
    resolution_status TEXT,   -- resolved | cycle | too_deep | unresolved_reference
    PRIMARY KEY (run_id, field_id)
);

CREATE TABLE IF NOT EXISTS metric_groups (
    run_id          TEXT,
    group_id        TEXT,
    canonical_label TEXT,
    confidence      TEXT,
    method          TEXT,
    PRIMARY KEY (run_id, group_id)
);

CREATE TABLE IF NOT EXISTS metric_variants (
    run_id          TEXT,
    group_id        TEXT,
    field_id        TEXT,
    normalized_hash TEXT,
    usage_rank      INTEGER,
    view_count      INTEGER,
    workbook_count  INTEGER,
    is_dominant     INTEGER,
    PRIMARY KEY (run_id, group_id, field_id)
);

CREATE TABLE IF NOT EXISTS flags (
    run_id       TEXT,
    flag_id      TEXT,
    severity     TEXT,
    confidence   TEXT,
    facet        TEXT,
    domain       TEXT,
    evidence_json TEXT,
    count        INTEGER,
    created_at   TEXT,
    PRIMARY KEY (run_id, flag_id, domain)
);

CREATE TABLE IF NOT EXISTS coverage (
    run_id  TEXT,
    measure TEXT,
    status  TEXT,     -- ok | partial | failed | skipped
    reason  TEXT,
    PRIMARY KEY (run_id, measure)
);

-- interview capture (M6, build spec section 10). A second input to the same
-- store, joined at scoring time. The scan never overwrites these and these
-- never overwrite the scan: where both exist, the scan wins and the interview
-- response is kept as corroboration or (via INT-01) conflict.

CREATE TABLE IF NOT EXISTS interview_responses (
    run_id        TEXT,
    facet_id      TEXT,
    score         INTEGER,
    evidence_note TEXT,
    source_role   TEXT,     -- data_platform_lead | analytics_leader | security | ...
    source_name   TEXT,     -- optional, excluded from the presentation build
    captured_at   TEXT,
    captured_by   TEXT,
    confidence    TEXT,     -- reported
    PRIMARY KEY (run_id, facet_id, source_role)
);

-- score output (M6). Scoring is deterministic over the store, but the CLI runs
-- `score` and `report` as separate steps, so the computed register is persisted
-- as the JSON contract shape (build spec 9.6) rather than re-normalized into
-- columns -- under-normalize rather than over-normalize.

CREATE TABLE IF NOT EXISTS score_output (
    run_id       TEXT PRIMARY KEY,
    findings_json TEXT,
    created_at   TEXT
);

-- operational: resumable shard state (build brief M2: "persist shard
-- completion state so a restart resumes"). Not a domain table.

CREATE TABLE IF NOT EXISTS extract_shards (
    run_id       TEXT,
    shard_key    TEXT,
    query_name   TEXT,
    scope_id     TEXT,
    page_size    INTEGER,
    cursor       TEXT,
    status       TEXT,     -- pending | in_progress | complete | failed
    node_count   INTEGER DEFAULT 0,
    subdivisions INTEGER DEFAULT 0,
    updated_at   TEXT,
    PRIMARY KEY (run_id, shard_key)
);
