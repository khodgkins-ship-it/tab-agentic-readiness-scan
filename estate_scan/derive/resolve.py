"""Recursive formula resolution to base columns (build spec section 7.1).

A calculation that references another calculation is not comparable until it is
resolved to base columns, so a variant like ``[Rev Net] * [FX Rate]`` must be
expanded through ``Rev Net`` down to the underlying ``SUM([Amount])`` before it
can be hashed and compared with a variant that inlines the same logic.

The two real pitfalls, both from the spec:

* **Scope.** Field references appear by name in brackets and names collide across
  data sources, so the token map is built per data source and resolution never
  crosses a source boundary.
* **Ambiguity.** A formula may reference a field's caption rather than its name.
  We build the map from both (captions are absent in the current fixtures) and,
  when a name resolves to more than one field in its source, we refuse to guess:
  the reference is left unexpanded and the field is recorded as
  ``unresolved_reference`` rather than silently binding to an arbitrary field.

Nothing here reads the fixture's ground-truth ``_ref_field_ids``; references are
rediscovered by parsing ``[...]`` tokens out of the formula text, which is what a
live scan would have to do.

Status is recorded per field and no field is ever dropped silently: a high
unresolved rate is itself a finding about estate complexity, so the caller reports
the counts.
"""

import re

from .normalize import formula_hash

MAX_DEPTH = 12  # spec default; a chain deeper than this is recorded too_deep.

RESOLVED = "resolved"
UNRESOLVED = "unresolved_reference"
TOO_DEEP = "too_deep"
CYCLE = "cycle"

# Worst-wins precedence when a field's own status must absorb its children's.
# A cycle is the most fundamental defect, then depth exhaustion, then a dangling
# reference; a field is only "resolved" when nothing below it was worse.
_RANK = {RESOLVED: 0, UNRESOLVED: 1, TOO_DEEP: 2, CYCLE: 3}

_BRACKET_RE = re.compile(r"\[[^\]]*\]")


def _worse(a, b):
    # type: (str, str) -> str
    return a if _RANK[a] >= _RANK[b] else b


class _SourceIndex(object):
    """Per-data-source token map from a lowercased name (or caption) to field.

    A name that maps to more than one field is ambiguous; callers must not bind
    it. Captions are supported for the day the schema exposes them; today they
    are simply absent.
    """

    __slots__ = ("by_id", "name_index", "ambiguous")

    def __init__(self):
        self.by_id = {}          # type: dict
        self.name_index = {}     # type: dict
        self.ambiguous = set()   # type: set

    def add(self, field):
        # type: (dict) -> None
        self.by_id[field["id"]] = field
        for key in (field.get("name"), field.get("caption")):
            if not key:
                continue
            token = key.strip().lower()
            self.name_index.setdefault(token, set()).add(field["id"])

    def finalize(self):
        # type: () -> None
        for token, ids in self.name_index.items():
            if len(ids) > 1:
                self.ambiguous.add(token)

    def lookup(self, token_name):
        # type: (str) -> tuple
        """Return (field_id, ambiguous). field_id is None when unknown."""
        key = token_name.strip().lower()
        if key in self.ambiguous:
            return None, True
        ids = self.name_index.get(key)
        if not ids:
            return None, False
        return next(iter(ids)), False


def _build_indexes(fields):
    # type: (list) -> dict
    indexes = {}  # type: dict
    for f in fields:
        ds = f["datasource_id"]
        idx = indexes.get(ds)
        if idx is None:
            idx = _SourceIndex()
            indexes[ds] = idx
        idx.add(f)
    for idx in indexes.values():
        idx.finalize()
    return indexes


def _direct_refs(field, idx):
    # type: (dict, _SourceIndex) -> list
    """Field ids this field references directly (rediscovered from the text)."""
    refs = []
    seen = set()
    for m in _BRACKET_RE.finditer(field.get("formula") or ""):
        rid, ambiguous = idx.lookup(m.group()[1:-1])
        if rid and not ambiguous and rid not in seen:
            seen.add(rid)
            refs.append(rid)
    return refs


def _resolve(field, idx, depth, seen):
    # type: (dict, _SourceIndex, int, frozenset) -> tuple
    """Return (resolved_text, status, deepest_frame_depth) for one field.

    Mirrors the spec pseudocode: a field already on the current path is a cycle;
    a frame past MAX_DEPTH is too deep; otherwise every bracketed reference to a
    calculated field is expanded in parentheses and worse-case status bubbles up.
    """
    formula = field.get("formula") or ""
    if field["id"] in seen:
        return formula, CYCLE, depth
    if depth > MAX_DEPTH:
        return formula, TOO_DEEP, depth

    child_seen = seen | {field["id"]}
    state = {"status": RESOLVED, "deepest": depth}

    def repl(m):
        token = m.group()
        rid, ambiguous = idx.lookup(token[1:-1])
        if ambiguous or rid is None:
            state["status"] = _worse(state["status"], UNRESOLVED)
            return token  # never guess which field an ambiguous name meant
        ref = idx.by_id[rid]
        if not ref.get("is_calculated"):
            return token  # base column: terminal, leave as-is
        sub_text, sub_status, sub_deep = _resolve(ref, idx, depth + 1, child_seen)
        state["status"] = _worse(state["status"], sub_status)
        if sub_deep > state["deepest"]:
            state["deepest"] = sub_deep
        return "(" + sub_text + ")"

    resolved = _BRACKET_RE.sub(repl, formula)
    return resolved, state["status"], state["deepest"]


def resolve_all(store, run_id):
    # type: (object, str) -> dict
    """Resolve every calculated field for a run, writing resolved_formulas and
    the rediscovered field_refs graph. Returns a status-count summary."""
    fields = [dict(r) for r in store.fields_for_run(run_id)]
    indexes = _build_indexes(fields)

    store.clear_resolved(run_id)
    summary = {RESOLVED: 0, UNRESOLVED: 0, TOO_DEEP: 0, CYCLE: 0,
               "calculated": 0, "ambiguous_refs": 0}

    for f in fields:
        ds = f["datasource_id"]
        idx = indexes[ds]
        # field_refs is a rediscovered fact for both calculated and column
        # references; record direct edges for calculated fields.
        if f.get("is_calculated"):
            for rid in _direct_refs(f, idx):
                store.save_field_ref(run_id, f["id"], rid)
        else:
            continue

        summary["calculated"] += 1
        text, status, deepest = _resolve(f, idx, 0, frozenset())
        # A calculated field occupies one level itself, so a leaf calc is depth
        # 1 (matches the fixture generator's ground-truth depth convention).
        resolution_depth = deepest + 1
        store.save_resolved_formula(
            run_id, f["id"], text, formula_hash(text),
            resolution_depth, status)
        summary[status] += 1
        # count ambiguous references encountered for the report-back
        for m in _BRACKET_RE.finditer(f.get("formula") or ""):
            _, ambiguous = idx.lookup(m.group()[1:-1])
            if ambiguous:
                summary["ambiguous_refs"] += 1

    store.commit()
    return summary
