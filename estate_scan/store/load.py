"""The store: SQLite access plus the API-envelope -> table mapping.

All writes go through here. Loaders map the projected public node shapes
(exactly what `clients/*.py` return) into the normalized tables in schema.sql.
Every loader uses INSERT OR REPLACE keyed on the row's primary key, so
re-processing a page during a resume overwrites rather than duplicates.

This module never issues an API call. Read-only-against-Tableau is a client
concern; write-locally is this module's only job.
"""

import json
import os
import sqlite3
from typing import Dict, List, Optional, Tuple

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def _b(value):
    # type: (object) -> Optional[int]
    """SQLite-friendly boolean (None stays None)."""
    if value is None:
        return None
    return 1 if value else 0


class Store(object):
    def __init__(self, conn):
        # type: (sqlite3.Connection) -> None
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self._project_map_cache = {}  # type: Dict[str, Dict[str, str]]

    @classmethod
    def open(cls, db_path):
        # type: (str) -> Store
        if db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(db_path))
            if parent and not os.path.isdir(parent):
                os.makedirs(parent)
        conn = sqlite3.connect(db_path)
        store = cls(conn)
        store.init_schema()
        return store

    def init_schema(self):
        # type: () -> None
        with open(_SCHEMA_PATH, "r") as fh:
            self.conn.executescript(fh.read())
        self.conn.commit()

    def commit(self):
        # type: () -> None
        self.conn.commit()

    def close(self):
        # type: () -> None
        self.conn.close()

    # -- run lifecycle -------------------------------------------------------
    def start_run(self, run_id, meta):
        # type: (str, dict) -> None
        self.conn.execute(
            "INSERT OR IGNORE INTO runs (run_id) VALUES (?)", (run_id,))
        self.conn.execute(
            "UPDATE runs SET site_id=?, site_name=?, deployment_type=?, "
            "adoption_source=?, started_at=COALESCE(started_at, ?), mode=?, "
            "tool_version=?, query_set_version=?, model_pass=? WHERE run_id=?",
            (meta.get("site_id"), meta.get("site_name"),
             meta.get("deployment_type"), meta.get("adoption_source"),
             meta.get("started_at"), meta.get("mode"),
             meta.get("tool_version"), meta.get("query_set_version"),
             _b(meta.get("model_pass")), run_id))
        self.conn.commit()

    def finish_run(self, run_id, completed_at, coverage_json):
        # type: (str, str, str) -> None
        self.conn.execute(
            "UPDATE runs SET completed_at=?, coverage_json=? WHERE run_id=?",
            (completed_at, coverage_json, run_id))
        self.conn.commit()

    def set_run_config(self, run_id, config_json):
        # type: (str, str) -> None
        self.conn.execute("UPDATE runs SET config_json=? WHERE run_id=?",
                          (config_json, run_id))
        self.conn.commit()

    def run_config(self, run_id):
        # type: (str) -> Optional[dict]
        """The config `scan` persisted (declared domains, target stages, core
        metrics). `score` reads it back so the run carries its own scope."""
        cur = self.conn.execute(
            "SELECT config_json FROM runs WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        if row is None or row["config_json"] is None:
            return None
        return json.loads(row["config_json"])

    def get_run(self, run_id):
        # type: (str) -> Optional[sqlite3.Row]
        cur = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
        return cur.fetchone()

    def latest_run_id(self):
        # type: () -> Optional[str]
        """The most recently started run (the CLI subcommands operate on one
        run per store, so `interview`/`score`/`report` resolve it here)."""
        cur = self.conn.execute(
            "SELECT run_id FROM runs ORDER BY COALESCE(started_at,'') DESC, "
            "run_id DESC LIMIT 1")
        row = cur.fetchone()
        return row["run_id"] if row else None

    # -- project name -> id resolution --------------------------------------
    def _project_map(self, run_id):
        # type: (str) -> Dict[str, str]
        cur = self.conn.execute(
            "SELECT id, name FROM projects WHERE run_id=?", (run_id,))
        return {row["name"]: row["id"] for row in cur.fetchall()}

    # -- loaders -------------------------------------------------------------
    def load_projects(self, run_id, nodes):
        # type: (str, List[dict]) -> int
        # Two passes: insert rows, then resolve parentProjectName -> parent id.
        for n in nodes:
            self.conn.execute(
                "INSERT OR REPLACE INTO projects "
                "(run_id, id, name, parent_id, locked_permissions) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, n["id"], n.get("name"), None, None))
        name_to_id = self._project_map(run_id)
        for n in nodes:
            parent_name = n.get("parentProjectName")
            if parent_name and parent_name in name_to_id:
                self.conn.execute(
                    "UPDATE projects SET parent_id=? WHERE run_id=? AND id=?",
                    (name_to_id[parent_name], run_id, n["id"]))
        self._project_map_cache.pop(run_id, None)
        return len(nodes)

    def load_datasources(self, run_id, nodes):
        # type: (str, List[dict]) -> int
        if run_id not in self._project_map_cache:
            self._project_map_cache[run_id] = self._project_map(run_id)
        pmap = self._project_map_cache[run_id]
        for n in nodes:
            project_name = n.get("projectName")
            self.conn.execute(
                "INSERT OR REPLACE INTO datasources "
                "(run_id, id, luid, name, kind, project_id, project_name, owner, "
                " is_certified, certification_note, has_extract, field_count, "
                " upstream_table_count, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, n["id"], n.get("luid"), n.get("name"), "published",
                 pmap.get(project_name), project_name,
                 (n.get("owner") or {}).get("username"),
                 _b(n.get("isCertified")), n.get("certificationNote"),
                 _b(n.get("hasExtracts")),
                 (n.get("fieldsConnection") or {}).get("totalCount"),
                 len(n.get("upstreamTables") or []),
                 n.get("createdAt"), n.get("updatedAt")))
            self._load_ds_lineage(run_id, n)
        return len(nodes)

    def _load_ds_lineage(self, run_id, ds):
        # type: (str, dict) -> None
        ds_id = ds["id"]
        for t in ds.get("upstreamTables") or []:
            phys = t.get("fullName") or t.get("id")
            if not phys:
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO lineage "
                "(run_id, downstream_type, downstream_id, upstream_type, "
                " upstream_id, upstream_label, depth) VALUES (?,?,?,?,?,?,?)",
                (run_id, "datasource", ds_id, "table", phys,
                 t.get("fullName"), 1))
        for up in ds.get("upstreamDatasources") or []:
            if not up.get("id"):
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO lineage "
                "(run_id, downstream_type, downstream_id, upstream_type, "
                " upstream_id, upstream_label, depth) VALUES (?,?,?,?,?,?,?)",
                (run_id, "datasource", ds_id, "datasource", up["id"],
                 up.get("name"), 1))

    def load_workbooks(self, run_id, nodes):
        # type: (str, List[dict]) -> int
        if run_id not in self._project_map_cache:
            self._project_map_cache[run_id] = self._project_map(run_id)
        pmap = self._project_map_cache[run_id]
        for n in nodes:
            project_name = n.get("projectName")
            self.conn.execute(
                "INSERT OR REPLACE INTO workbooks "
                "(run_id, id, luid, name, project_id, project_name, owner, "
                " created_at, updated_at, sheet_count, embedded_ds_count) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, n["id"], n.get("luid"), n.get("name"),
                 pmap.get(project_name), project_name,
                 (n.get("owner") or {}).get("username"),
                 n.get("createdAt"), n.get("updatedAt"),
                 len(n.get("sheets") or []),
                 len(n.get("embeddedDatasources") or [])))
            for up in n.get("upstreamDatasources") or []:
                if not up.get("id"):
                    continue
                self.conn.execute(
                    "INSERT OR REPLACE INTO lineage "
                    "(run_id, downstream_type, downstream_id, upstream_type, "
                    " upstream_id, upstream_label, depth) VALUES (?,?,?,?,?,?,?)",
                    (run_id, "workbook", n["id"], "datasource", up["id"],
                     up.get("name"), 1))
            for emb in n.get("embeddedDatasources") or []:
                if not emb.get("id"):
                    continue
                self.conn.execute(
                    "INSERT OR REPLACE INTO lineage "
                    "(run_id, downstream_type, downstream_id, upstream_type, "
                    " upstream_id, upstream_label, depth) VALUES (?,?,?,?,?,?,?)",
                    (run_id, "workbook", n["id"], "embedded_datasource",
                     emb["id"], emb.get("name"), 1))
        return len(nodes)

    def load_fields(self, run_id, datasource_id, nodes):
        # type: (str, str, List[dict]) -> int
        for n in nodes:
            typename = n.get("__typename")
            is_calc = typename == "CalculatedField"
            self.conn.execute(
                "INSERT OR REPLACE INTO fields "
                "(run_id, id, name, description, datasource_id, field_type, "
                " data_type, role, formula, is_calculated) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, n["id"], n.get("name"), n.get("description"),
                 datasource_id, typename, n.get("dataType"), n.get("role"),
                 n.get("formula"), _b(is_calc)))
            for s in n.get("sheetsUsedIn") or []:
                wb = s.get("workbook") or {}
                self.conn.execute(
                    "INSERT OR REPLACE INTO field_usage "
                    "(run_id, field_id, sheet_id, workbook_id) VALUES (?,?,?,?)",
                    (run_id, n["id"], s.get("id") or "",
                     wb.get("id") or wb.get("luid") or ""))
        return len(nodes)

    def load_usage_events(self, run_id, items):
        # type: (str, List[dict]) -> int
        for e in items:
            self.conn.execute(
                "INSERT OR REPLACE INTO usage_events "
                "(run_id, workbook_id, workbook_luid, user_id, event_date, "
                " event_count, last_viewed_days_ago) VALUES (?,?,?,?,?,?,?)",
                (run_id, e.get("workbook_id"), e.get("workbook_luid"),
                 e.get("user_id"), e.get("event_date"),
                 e.get("views", e.get("event_count")),
                 e.get("last_viewed_days_ago")))
        return len(items)

    # -- derive: read fields, write resolved formulas & refs -----------------
    def fields_for_run(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT id, name, description, datasource_id, field_type, "
            "data_type, role, formula, is_calculated FROM fields "
            "WHERE run_id=? ORDER BY datasource_id, id", (run_id,))
        return cur.fetchall()

    def clear_resolved(self, run_id):
        # type: (str) -> None
        """Drop prior derivation output so a re-run is clean, not additive."""
        self.conn.execute(
            "DELETE FROM resolved_formulas WHERE run_id=?", (run_id,))
        self.conn.execute("DELETE FROM field_refs WHERE run_id=?", (run_id,))

    def save_resolved_formula(self, run_id, field_id, resolved_formula,
                              normalized_hash, resolution_depth,
                              resolution_status):
        # type: (str, str, Optional[str], str, int, str) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO resolved_formulas "
            "(run_id, field_id, resolved_formula, normalized_hash, "
            " resolution_depth, resolution_status) VALUES (?,?,?,?,?,?)",
            (run_id, field_id, resolved_formula, normalized_hash,
             resolution_depth, resolution_status))

    def save_field_ref(self, run_id, field_id, referenced_field_id):
        # type: (str, str, str) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO field_refs "
            "(run_id, field_id, referenced_field_id) VALUES (?,?,?)",
            (run_id, field_id, referenced_field_id))

    def resolved_formulas(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM resolved_formulas WHERE run_id=? ORDER BY field_id",
            (run_id,))
        return cur.fetchall()

    def resolution_status_counts(self, run_id):
        # type: (str) -> Dict[str, int]
        cur = self.conn.execute(
            "SELECT resolution_status, COUNT(*) AS c FROM resolved_formulas "
            "WHERE run_id=? GROUP BY resolution_status", (run_id,))
        return {row["resolution_status"]: row["c"] for row in cur.fetchall()}

    def field_refs(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM field_refs WHERE run_id=? "
            "ORDER BY field_id, referenced_field_id", (run_id,))
        return cur.fetchall()

    # -- derive: concept grouping (M4) --------------------------------------
    def calc_fields_resolved(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        """Calculated fields joined to their M3 resolution, the input to
        grouping. Ordered by field id so grouping is deterministic."""
        cur = self.conn.execute(
            "SELECT f.id AS field_id, f.name AS name, f.formula AS formula, "
            "       f.datasource_id AS datasource_id, "
            "       r.resolved_formula AS resolved_formula, "
            "       r.normalized_hash AS normalized_hash, "
            "       r.resolution_status AS resolution_status "
            "FROM fields f "
            "LEFT JOIN resolved_formulas r "
            "  ON r.run_id = f.run_id AND r.field_id = f.id "
            "WHERE f.run_id=? AND f.is_calculated=1 "
            "ORDER BY f.id", (run_id,))
        return cur.fetchall()

    def field_view_counts(self, run_id):
        # type: (str) -> Dict[str, Dict[str, int]]
        """Per calculated field, views and distinct workbook count, joined
        through field usage to usage_events.

        A field used on several sheets of one workbook counts that workbook's
        views once: dedupe (field_id, workbook_id) before summing (build brief
        M4). Workbooks with no usage_events row contribute nothing (inner join),
        which is correct -- an unmeasured workbook is not a zero-view workbook.
        """
        cur = self.conn.execute(
            "SELECT fu.field_id AS field_id, "
            "       COALESCE(SUM(ue.event_count), 0) AS views, "
            "       COUNT(*) AS workbooks "
            "FROM (SELECT DISTINCT field_id, workbook_id FROM field_usage "
            "      WHERE run_id=?) fu "
            "JOIN usage_events ue "
            "  ON ue.run_id=? AND ue.workbook_id = fu.workbook_id "
            "GROUP BY fu.field_id", (run_id, run_id))
        return {row["field_id"]: {"views": row["views"],
                                  "workbooks": row["workbooks"]}
                for row in cur.fetchall()}

    def clear_groups(self, run_id):
        # type: (str) -> None
        """Drop prior grouping/ranking output so a re-run is clean."""
        self.conn.execute("DELETE FROM metric_groups WHERE run_id=?", (run_id,))
        self.conn.execute("DELETE FROM metric_variants WHERE run_id=?", (run_id,))

    def save_metric_group(self, run_id, group_id, canonical_label, confidence,
                          method):
        # type: (str, str, str, str, str) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO metric_groups "
            "(run_id, group_id, canonical_label, confidence, method) "
            "VALUES (?,?,?,?,?)",
            (run_id, group_id, canonical_label, confidence, method))

    def save_metric_variant(self, run_id, group_id, field_id, normalized_hash,
                            usage_rank, view_count, workbook_count, is_dominant):
        # type: (str, str, str, str, Optional[int], int, int, int) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO metric_variants "
            "(run_id, group_id, field_id, normalized_hash, usage_rank, "
            " view_count, workbook_count, is_dominant) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, group_id, field_id, normalized_hash, usage_rank,
             view_count, workbook_count, _b(is_dominant)))

    def update_variant_usage(self, run_id, group_id, field_id, usage_rank,
                             view_count, workbook_count, is_dominant):
        # type: (str, str, str, int, int, int, int) -> None
        self.conn.execute(
            "UPDATE metric_variants SET usage_rank=?, view_count=?, "
            "workbook_count=?, is_dominant=? "
            "WHERE run_id=? AND group_id=? AND field_id=?",
            (usage_rank, view_count, workbook_count, _b(is_dominant),
             run_id, group_id, field_id))

    def metric_groups(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM metric_groups WHERE run_id=? ORDER BY group_id",
            (run_id,))
        return cur.fetchall()

    def metric_variants(self, run_id, group_id=None):
        # type: (str, Optional[str]) -> List[sqlite3.Row]
        if group_id is None:
            cur = self.conn.execute(
                "SELECT * FROM metric_variants WHERE run_id=? "
                "ORDER BY group_id, usage_rank, field_id", (run_id,))
        else:
            cur = self.conn.execute(
                "SELECT * FROM metric_variants WHERE run_id=? AND group_id=? "
                "ORDER BY usage_rank, field_id", (run_id, group_id))
        return cur.fetchall()

    # -- shard state ---------------------------------------------------------
    def get_shard(self, run_id, shard_key):
        # type: (str, str) -> Optional[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM extract_shards WHERE run_id=? AND shard_key=?",
            (run_id, shard_key))
        return cur.fetchone()

    def save_shard(self, run_id, shard_key, query_name, scope_id, page_size,
                   cursor, status, node_count, subdivisions, updated_at):
        # type: (str, str, str, Optional[str], int, Optional[str], str, int, int, str) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO extract_shards "
            "(run_id, shard_key, query_name, scope_id, page_size, cursor, "
            " status, node_count, subdivisions, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, shard_key, query_name, scope_id, page_size, cursor,
             status, node_count, subdivisions, updated_at))

    def all_shards(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM extract_shards WHERE run_id=? ORDER BY shard_key",
            (run_id,))
        return cur.fetchall()

    # -- coverage ------------------------------------------------------------
    def record_coverage(self, run_id, measure, status, reason=""):
        # type: (str, str, str, str) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO coverage (run_id, measure, status, reason) "
            "VALUES (?,?,?,?)", (run_id, measure, status, reason))
        self.conn.commit()

    def coverage(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM coverage WHERE run_id=? ORDER BY measure", (run_id,))
        return cur.fetchall()

    # -- flags (M5) ---------------------------------------------------------
    def clear_flags(self, run_id):
        # type: (str) -> None
        self.conn.execute("DELETE FROM flags WHERE run_id=?", (run_id,))

    def clear_flag(self, run_id, flag_id):
        # type: (str, str) -> None
        """Clear one flag id (M6 uses this so re-scoring rebuilds its INT-01
        rows without disturbing the M5 flags the flag engine wrote)."""
        self.conn.execute("DELETE FROM flags WHERE run_id=? AND flag_id=?",
                          (run_id, flag_id))

    def save_flag(self, run_id, flag_id, severity, confidence, facet, domain,
                  evidence_json, count, created_at):
        # type: (str, str, str, str, str, str, str, int, str) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO flags "
            "(run_id, flag_id, severity, confidence, facet, domain, "
            " evidence_json, count, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, flag_id, severity, confidence, facet, domain,
             evidence_json, count, created_at))

    def flags(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM flags WHERE run_id=? ORDER BY flag_id, domain",
            (run_id,))
        return cur.fetchall()

    # -- flag measures (M5) -------------------------------------------------
    # Each returns raw values; thresholds and firing live in the flag engine so
    # rules.yaml can change firing with no code edit.

    def calc_field_formulas(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        """id, name, formula for calculated fields (SEC-01 scans these)."""
        cur = self.conn.execute(
            "SELECT id, name, formula FROM fields "
            "WHERE run_id=? AND is_calculated=1 ORDER BY id", (run_id,))
        return cur.fetchall()

    def field_description_coverage(self, run_id):
        # type: (str) -> Tuple[int, int]
        """(described, total) over all fields -- SEM-03 description coverage."""
        total = self.conn.execute(
            "SELECT COUNT(*) c FROM fields WHERE run_id=?", (run_id,)
        ).fetchone()["c"]
        described = self.conn.execute(
            "SELECT COUNT(*) c FROM fields WHERE run_id=? "
            "AND TRIM(COALESCE(description,''))<>''", (run_id,)
        ).fetchone()["c"]
        return described, total

    def workbook_ds_ref_counts(self, run_id):
        # type: (str) -> Tuple[int, int]
        """(embedded, published) datasource references from workbooks, counted
        through lineage -- DF-01 embedded share."""
        emb = self.conn.execute(
            "SELECT COUNT(*) c FROM lineage WHERE run_id=? "
            "AND downstream_type='workbook' AND upstream_type='embedded_datasource'",
            (run_id,)).fetchone()["c"]
        pub = self.conn.execute(
            "SELECT COUNT(*) c FROM lineage WHERE run_id=? "
            "AND downstream_type='workbook' AND upstream_type='datasource'",
            (run_id,)).fetchone()["c"]
        return emb, pub

    def upstream_table_fanout(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        """Per upstream table, how many published sources trace to it, most
        first -- DF-02."""
        cur = self.conn.execute(
            "SELECT upstream_id, upstream_label, "
            "       COUNT(DISTINCT downstream_id) AS sources "
            "FROM lineage WHERE run_id=? "
            "AND downstream_type='datasource' AND upstream_type='table' "
            "GROUP BY upstream_id, upstream_label ORDER BY sources DESC, upstream_id",
            (run_id,))
        return cur.fetchall()

    def published_on_published_edges(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        """downstream_id -> upstream_id edges where both are published sources.
        The engine computes the longest chain -- DF-03."""
        cur = self.conn.execute(
            "SELECT downstream_id, upstream_id, upstream_label FROM lineage "
            "WHERE run_id=? AND downstream_type='datasource' "
            "AND upstream_type='datasource' ORDER BY downstream_id, upstream_id",
            (run_id,))
        return cur.fetchall()

    def zero_view_workbooks(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        """Workbooks with no measured views (EST-01). LEFT JOIN so a workbook
        with no usage_events row counts as zero-view, not as unmeasured-absent."""
        cur = self.conn.execute(
            "SELECT w.id AS id, w.name AS name, w.project_name AS project_name "
            "FROM workbooks w "
            "LEFT JOIN usage_events ue "
            "  ON ue.run_id=w.run_id AND ue.workbook_id=w.id "
            "WHERE w.run_id=? AND COALESCE(ue.event_count,0)=0 "
            "ORDER BY w.id", (run_id,))
        return cur.fetchall()

    def workbook_view_counts(self, run_id):
        # type: (str) -> List[int]
        """Per-workbook view totals, for concentration measures (ADO-02)."""
        cur = self.conn.execute(
            "SELECT COALESCE(event_count,0) AS v FROM usage_events WHERE run_id=?",
            (run_id,))
        return [row["v"] for row in cur.fetchall()]

    # -- read helpers for the planner / tests -------------------------------
    def datasource_ids(self, run_id):
        # type: (str) -> List[str]
        cur = self.conn.execute(
            "SELECT id FROM datasources WHERE run_id=? ORDER BY id", (run_id,))
        return [row["id"] for row in cur.fetchall()]

    def count(self, table, run_id):
        # type: (str, str) -> int
        # table is a fixed internal identifier, never user input.
        cur = self.conn.execute(
            "SELECT COUNT(*) AS c FROM %s WHERE run_id=?" % table, (run_id,))
        return cur.fetchone()["c"]

    # -- scoring measures (M6) ----------------------------------------------
    def dominant_group_share(self, run_id):
        # type: (str) -> Tuple[int, int]
        """(dominant groups, total groups) -- the semantic.singularity measure.
        A group is dominant when its rank-1 variant carries the group (M4)."""
        total = self.conn.execute(
            "SELECT COUNT(*) c FROM metric_groups WHERE run_id=?", (run_id,)
        ).fetchone()["c"]
        dominant = self.conn.execute(
            "SELECT COUNT(DISTINCT group_id) c FROM metric_variants "
            "WHERE run_id=? AND is_dominant=1", (run_id,)
        ).fetchone()["c"]
        return dominant, total

    def workbook_count(self, run_id):
        # type: (str) -> int
        return self.conn.execute(
            "SELECT COUNT(*) c FROM workbooks WHERE run_id=?", (run_id,)
        ).fetchone()["c"]

    # -- interview capture (M6) ---------------------------------------------
    def clear_interview(self, run_id):
        # type: (str) -> None
        self.conn.execute("DELETE FROM interview_responses WHERE run_id=?",
                          (run_id,))

    def save_interview_response(self, run_id, facet_id, score, evidence_note,
                                source_role, source_name, captured_at,
                                captured_by, confidence):
        # type: (str, str, Optional[int], str, str, str, str, str, str) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO interview_responses "
            "(run_id, facet_id, score, evidence_note, source_role, source_name, "
            " captured_at, captured_by, confidence) VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, facet_id, score, evidence_note, source_role, source_name,
             captured_at, captured_by, confidence))

    def interview_responses(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM interview_responses WHERE run_id=? "
            "ORDER BY facet_id, source_role", (run_id,))
        return cur.fetchall()

    # -- score output (M6) --------------------------------------------------
    def save_score_output(self, run_id, findings_json, created_at):
        # type: (str, str, str) -> None
        self.conn.execute(
            "INSERT OR REPLACE INTO score_output "
            "(run_id, findings_json, created_at) VALUES (?,?,?)",
            (run_id, findings_json, created_at))

    def score_output(self, run_id):
        # type: (str) -> Optional[sqlite3.Row]
        cur = self.conn.execute(
            "SELECT * FROM score_output WHERE run_id=?", (run_id,))
        return cur.fetchone()

    # -- report read helpers (M7) -------------------------------------------
    # The findings assembler (report/findings.py) reads through these so the
    # SQL stays in the store layer, consistent with the flag measures above.

    def run_meta(self, run_id):
        # type: (str) -> Optional[sqlite3.Row]
        """Run-level metadata for the coverage panel and report header."""
        cur = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
        return cur.fetchone()

    def group_variant_detail(self, run_id, group_id):
        # type: (str, str) -> List[sqlite3.Row]
        """Every variant of a group with the detail the drill-down needs: the
        field name and resolved formula, usage rank and counts, and the owning
        data source and its owner. Ordered by usage rank."""
        cur = self.conn.execute(
            "SELECT mv.field_id AS field_id, f.name AS field_name, "
            "       mv.usage_rank AS usage_rank, mv.view_count AS view_count, "
            "       mv.workbook_count AS workbook_count, "
            "       mv.is_dominant AS is_dominant, "
            "       mv.normalized_hash AS normalized_hash, "
            "       rf.resolved_formula AS resolved_formula, "
            "       rf.resolution_status AS resolution_status, "
            "       ds.name AS datasource_name, ds.owner AS owner "
            "FROM metric_variants mv "
            "LEFT JOIN fields f ON f.run_id=mv.run_id AND f.id=mv.field_id "
            "LEFT JOIN resolved_formulas rf "
            "  ON rf.run_id=mv.run_id AND rf.field_id=mv.field_id "
            "LEFT JOIN datasources ds "
            "  ON ds.run_id=mv.run_id AND ds.id=f.datasource_id "
            "WHERE mv.run_id=? AND mv.group_id=? "
            "ORDER BY mv.usage_rank, mv.field_id", (run_id, group_id))
        return cur.fetchall()

    def group_workbook_count(self, run_id, group_id):
        # type: (str, str) -> int
        """Distinct workbooks any variant of the group is used in."""
        cur = self.conn.execute(
            "SELECT COUNT(DISTINCT fu.workbook_id) AS c "
            "FROM metric_variants mv "
            "JOIN field_usage fu "
            "  ON fu.run_id=mv.run_id AND fu.field_id=mv.field_id "
            "WHERE mv.run_id=? AND mv.group_id=? "
            "AND TRIM(COALESCE(fu.workbook_id,''))<>''", (run_id, group_id))
        return cur.fetchone()["c"]

    def calc_field_detail(self, run_id):
        # type: (str) -> List[sqlite3.Row]
        """Calculated fields with formula, owning source, and owner -- the
        input to the security-exposure finding (user-context functions are
        matched in Python, sharing SEC-01's function list)."""
        cur = self.conn.execute(
            "SELECT f.id AS id, f.name AS name, f.formula AS formula, "
            "       ds.name AS datasource_name, ds.owner AS owner "
            "FROM fields f "
            "LEFT JOIN datasources ds "
            "  ON ds.run_id=f.run_id AND ds.id=f.datasource_id "
            "WHERE f.run_id=? AND f.is_calculated=1 ORDER BY f.id", (run_id,))
        return cur.fetchall()

    def workbooks_for_fields(self, run_id, field_ids):
        # type: (str, List[str]) -> List[sqlite3.Row]
        """Distinct workbooks (id, name, owner) that use any of `field_ids`."""
        if not field_ids:
            return []
        marks = ",".join("?" for _ in field_ids)
        cur = self.conn.execute(
            "SELECT DISTINCT w.id AS id, w.name AS name, w.owner AS owner "
            "FROM field_usage fu "
            "JOIN workbooks w ON w.run_id=fu.run_id AND w.id=fu.workbook_id "
            "WHERE fu.run_id=? AND fu.field_id IN (%s) "
            "AND TRIM(COALESCE(fu.workbook_id,''))<>'' "
            "ORDER BY w.id" % marks, [run_id] + list(field_ids))
        return cur.fetchall()

    def total_measured_views(self, run_id):
        # type: (str) -> int
        cur = self.conn.execute(
            "SELECT COALESCE(SUM(event_count),0) AS v FROM usage_events "
            "WHERE run_id=?", (run_id,))
        return cur.fetchone()["v"]
