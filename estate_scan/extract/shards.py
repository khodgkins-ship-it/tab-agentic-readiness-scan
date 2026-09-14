"""Shard definitions and subdivision.

A shard is one resumable unit of extraction: a named query, an optional scope
(the parent id for per-datasource field extraction), the current cursor, and
the page size in force. The build spec's sharding order is project, then object
type, then cursor page; the prototype's fixture queries are global at the object
level and per-datasource for fields, which the manifest shard hints encode.

Subdivision is the load-bearing behaviour: when a page comes back partial
(node-limit warning), we do NOT advance the cursor. We halve the page size and
retry the same cursor, because a node limit counts total nodes returned
(including nested children), so fewer top-level rows means fewer total nodes.
"""

from typing import Optional

MIN_PAGE_SIZE = 1


class Shard(object):
    __slots__ = ("shard_key", "query_name", "scope_id", "scope_var",
                 "cursor_var", "first_var", "page_size", "cursor",
                 "status", "node_count", "subdivisions")

    def __init__(self, shard_key, query_name, page_size, cursor_var="after",
                 first_var="first", scope_id=None, scope_var=None):
        # type: (str, str, int, str, str, Optional[str], Optional[str]) -> None
        self.shard_key = shard_key
        self.query_name = query_name
        self.scope_id = scope_id
        self.scope_var = scope_var
        self.cursor_var = cursor_var
        self.first_var = first_var
        self.page_size = page_size
        self.cursor = None       # type: Optional[str]
        self.status = "pending"
        self.node_count = 0
        self.subdivisions = 0

    def variables(self):
        # type: () -> dict
        v = {self.first_var: self.page_size}
        if self.cursor is not None:
            v[self.cursor_var] = self.cursor
        if self.scope_var and self.scope_id is not None:
            v[self.scope_var] = self.scope_id
        return v

    def can_subdivide(self):
        # type: () -> bool
        return self.page_size > MIN_PAGE_SIZE

    def subdivide(self):
        # type: () -> None
        """Halve the page size and count the subdivision. Cursor is unchanged:
        the partial page is discarded and refetched smaller."""
        if not self.can_subdivide():
            raise ValueError(
                "shard %s already at minimum page size but still partial; a "
                "single node exceeds the limit" % self.shard_key)
        self.page_size = max(MIN_PAGE_SIZE, self.page_size // 2)
        self.subdivisions += 1

    def __repr__(self):
        return ("Shard(key=%r, query=%r, scope=%r, page_size=%d, cursor=%r, "
                "status=%r, nodes=%d, subdiv=%d)" % (
                    self.shard_key, self.query_name, self.scope_id,
                    self.page_size, self.cursor, self.status,
                    self.node_count, self.subdivisions))


def global_shard(query_name, hint):
    # type: (str, dict) -> Shard
    return Shard(shard_key=query_name, query_name=query_name,
                 page_size=hint["page_size"],
                 cursor_var=hint.get("cursor_var", "after"),
                 first_var=hint.get("first_var", "first"))


def scoped_shard(query_name, hint, scope_id):
    # type: (str, dict, str) -> Shard
    return Shard(shard_key="%s:%s" % (query_name, scope_id),
                 query_name=query_name, page_size=hint["page_size"],
                 cursor_var=hint.get("cursor_var", "after"),
                 first_var=hint.get("first_var", "first"),
                 scope_id=scope_id, scope_var=hint.get("scope_var"))
