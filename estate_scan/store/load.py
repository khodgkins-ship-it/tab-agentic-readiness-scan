"""The store: SQLite access plus the API-envelope -> table mapping.

All writes go through here. Loaders map the projected public node shapes
(exactly what `clients/*.py` return) into the normalized tables in schema.sql.
Every loader uses INSERT OR REPLACE keyed on the row's primary key, so
re-processing a page during a resume overwrites rather than duplicates.

This module never issues an API call. Read-only-against-Tableau is a client
concern; write-locally is this module's only job.
"""

import os
import sqlite3
from typing import Dict, List, Optional

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

    def get_run(self, run_id):
        # type: (str) -> Optional[sqlite3.Row]
        cur = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
        return cur.fetchone()

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
