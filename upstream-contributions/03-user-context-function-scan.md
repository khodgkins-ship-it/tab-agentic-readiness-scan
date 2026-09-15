# Contribution 3 — User-context function scan

**Upstream:** `tableau/tableau-metadata-explorer`
**Files:** `app/proxy/governance.py` (new analysis, alongside `duplicate_calculated_fields`)
**Kind:** feature — a governance analysis any admin would want; fits their dashboard
**Status:** prepared, **not opened**

---

## Why this belongs upstream

The metadata explorer already runs governance analyses over calculated fields
(`governance.py::duplicate_calculated_fields`). A closely related, generally
useful one is missing: **which calculated fields make their value depend on who
is viewing** — i.e. fields whose formula calls a Tableau user-context function
(`USERNAME()`, `ISMEMBEROF(...)`, `FULLNAME()`, `USERDOMAIN()`).

These fields are how row-level security and per-user entitlement logic get baked
into the *view layer* instead of being managed centrally. An admin wants to see
them because:

- they are a governance risk surface (access logic scattered across calc fields
  is hard to audit and easy to get wrong);
- they explain why a "single number" differs per viewer (a value that is
  viewer-dependent by construction, not a data-quality bug);
- they are a migration hazard (they behave differently, or not at all, when a
  workbook moves between sites/servers or when identities change).

It is general-purpose metadata analysis — no maturity-framework opinion in it —
so it belongs in the shared tool rather than our layer.

## Proposed change

Add a `user_context_fields()` analysis to `governance.py` that:

1. fetches `CalculatedField { id, name, formula }` (the same node type
   `duplicate_calculated_fields` already fetches — reuse that query/pagination,
   including the partial-response handling of Contribution 1);
2. flags each field whose formula matches a user-context function (word-boundary,
   case-insensitive, followed by `(`);
3. returns the count plus, per hit, the field and its containing datasource /
   workbook, so the dashboard can list "access rules living in the view layer".

The function set is small and well-known; keep it as a named constant so it is
easy to review and extend.

## Illustrative diff (not apply-ready — see README)

`app/proxy/governance.py`:

```diff
+import re
+
+# Tableau functions whose result depends on the viewer. A calc field invoking
+# one is entitlement / row-level-security logic living in the view layer.
+USER_CONTEXT_FUNCS = ["USERNAME", "ISMEMBEROF", "FULLNAME", "USERDOMAIN"]
+_UC_RE = re.compile(r"\b(" + "|".join(USER_CONTEXT_FUNCS) + r")\s*\(",
+                    re.IGNORECASE)
+
+
+def user_context_fields(client, site_luid=None):
+    """Calc fields whose formula depends on the viewer (RLS/entitlement logic
+    in the view layer). Reuses the CalculatedField fetch + partial-response
+    pagination that duplicate_calculated_fields uses."""
+    nodes = fetch_all_paginated(client, CALC_FIELDS_QUERY, {...})  # see #1
+    hits = []
+    for n in nodes:
+        formula = n.get("formula") or ""
+        m = _UC_RE.search(formula)
+        if m:
+            hits.append({
+                "id": n["id"],
+                "name": n.get("name"),
+                "function": m.group(1).upper(),
+                "datasource": n.get("datasource", {}).get("name"),
+            })
+    return {"count": len(hits), "fields": hits}
```

Wire it into the governance router/dashboard the same way
`duplicate_calculated_fields` is surfaced.

## Test that proves it

Feed calc-field nodes with known formulas: one `IF ISMEMBEROF('Finance') …`, one
`[Email] = USERNAME()`, one plain arithmetic formula, one that merely contains
the substring `username` in a comment/identifier but not as a call. Assert the
first two are flagged (with the right function name), the third is not, and the
fourth is not (word-boundary + `(` guards against false positives).

## How this repo already embodies the scan (reference for reviewers)

The scan ships here and drives a real finding:

- **The function set and matcher:** `estate_scan/derive/group.py:53`
  (`USER_CONTEXT_FUNCS = ["USERNAME", "ISMEMBEROF", "FULLNAME", "USERDOMAIN"]`)
  and the word-boundary `_UC_RE` (`group.py:55`) — the exact constant and regex
  the diff proposes.
- **The flag:** SEC-01 `formula_contains_user_context`
  (`estate_scan/flags/engine.py::_eval_user_context`, `engine.py:43`) scans
  resolved formulas and raises when access logic lives in the view layer.
- **Report surfacing:** `estate_scan/report/findings.py:256`
  (`user_context_field_count`) and the report renderers
  (`report/markdown.py:145`, `report/webapp.py:142`,
  `report/compare.py:26` — *"Access rules in the view layer"*).
- **The same list is reused for executability classification** in
  `estate_scan/derive/disagreement.py:40-64`: a resolved formula that depends on
  user context is `context_bound` — a single value would misrepresent it — which
  is the same insight from the analysis side.

Because the scan is proven against fixtures end to end here, the upstream version
is a straight port of a working analysis, not a design sketch.
