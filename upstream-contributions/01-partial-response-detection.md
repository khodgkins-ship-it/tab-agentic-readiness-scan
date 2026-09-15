# Contribution 1 — Uniform partial-response handling

**Upstream:** `tableau/tableau-metadata-explorer`
**Files:** `app/proxy/tableau_metadata.py`, `app/proxy/governance.py`, `app/proxy/router.py`
**Kind:** correctness fix (affects every consumer), not a feature
**Status:** prepared, **not opened**

---

## Problem (verified against source at R0)

Upstream *does* detect node-/time-limit partial responses — this was
under-claimed in our own early notes and R0 corrected it. `tableau_metadata.py`
has a `classify_result()` that recognises the warning-code family
(`NODE_LIMIT_EXCEEDED`, `TIME_LIMIT_EXCEEDED`, …): an HTTP 200 whose top-level
`errors[]` carry a known warning code **with `data` present** is a *partial*
result — usable, known-incomplete — and any other code or null `data` is fatal.

The bug is that detection is **not universal** and reaction is **inconsistent**:

- `classify_result()` is one code path, not a gate every response passes
  through. `execute()` returns raw responses without classifying them.
- The raw `/proxy/metadata` passthrough forwards a truncated 200 to the caller
  **as-is**, with no signal that it is incomplete.
- `governance.py::duplicate_calculated_fields` calls `execute()` and treats *any*
  `result.get('errors')` — including the very warning codes `classify_result`
  would call *partial* — as a **hard failure**. So a large tenant that trips a
  node limit gets an error instead of a subdivide-and-retry.
- Meanwhile `router.py::fetch_more` *does* react — it halves the page size on a
  limit warning. So two callers of the same API do opposite things.

Silently accepting truncated data is the single most dangerous failure mode for
any consumer of this client: an analysis then reports on a *subset* of the estate
as if it were the whole, with no indication. And hard-failing on a usable partial
throws away a result that could have been completed by subdividing.

## Proposed change

Make both steps uniform:

1. **Classify at the boundary.** Route every response through `classify_result()`
   inside `execute()` (or a thin `execute_classified()` the callers adopt), so no
   caller ever receives a raw, unclassified 200. The return value carries
   `partial: bool` and `warnings: [code]` alongside `data`.
2. **React consistently.** Callers act on `partial` the same way — subdivide the
   page and retry the same cursor until the page returns complete — instead of
   each caller choosing. `router.py::fetch_more` already does this; lift it into a
   shared helper and have `duplicate_calculated_fields` (and any other paginating
   caller) use it rather than hard-failing.
3. **Never forward truncated data silently.** The raw `/proxy/metadata`
   passthrough surfaces the partial state (a response flag / header) so a UI
   client knows the payload is incomplete.

## Illustrative diff (not apply-ready — see README)

`app/proxy/tableau_metadata.py` — classify inside `execute()` so no caller sees a raw truncated 200:

```diff
 def execute(self, query, variables=None):
     resp = self._post_metadata(query, variables)
-    return resp.json()
+    body = resp.json()
+    # Every response is classified here so no caller receives a raw,
+    # unclassified 200. classify_result() already knows the warning family;
+    # this just makes it the single boundary instead of one optional path.
+    return classify_result(resp.status_code, body)
```

`app/proxy/governance.py` — stop treating a usable partial as a hard failure:

```diff
 def duplicate_calculated_fields(...):
     result = client.execute(CALC_FIELDS_QUERY, variables)
-    if result.get('errors'):
-        raise MetadataError(result['errors'])
-    nodes = result['data']['...']['nodes']
+    # A warning-code error with data present is a *partial*, not a failure:
+    # subdivide and retry rather than discarding a usable (if incomplete) page.
+    if result.fatal:
+        raise MetadataError(result.error)
+    if result.partial:
+        nodes = fetch_all_paginated(client, CALC_FIELDS_QUERY, variables)
+    else:
+        nodes = result.data['...']['nodes']
```

`app/proxy/router.py` — lift the existing page-halving into the shared helper the above calls:

```diff
-def fetch_more(client, query, variables):
-    # ... local halving logic, only used here ...
+# fetch_all_paginated(): the one place that subdivides on a partial and retries
+# the same cursor to completion. router.fetch_more and governance both call it.
```

## Test that proves it

Mirror our own `tests/test_partial.py`: feed the client a mock transport that
returns a node-limit warning **with data** on the first call and a complete page
on the retry; assert (a) `execute()` reports `partial` (not a raw 200, not a
fatal error), and (b) the paginating caller subdivides and ultimately returns the
full node set. A second case: a fatal code (or null `data`) must raise, not
subdivide forever.

## How this repo already embodies the fix (reference for reviewers)

We centralised exactly this so the reviewer can see it working end to end:

- **One classifier at the boundary:** `estate_scan/clients/base.py::classify_graphql`
  mirrors `classify_result` and the warning-code set exactly
  (`GQL_WARNING_CODES`, `base.py:186`). *Every* response — fixture and live —
  goes through it; there is no unclassified path.
- **One place that reacts:** `estate_scan/extract/runner.py::_run_shard`
  (`runner.py:306`) is the only code that acts on `partial`: it never accepts the
  data, subdivides the shard (`shard.subdivide()`), and retries the same cursor,
  failing loudly only when a single node still exceeds the limit at minimum page
  size. Callers never each decide.
- **Forced in CI:** our partial-response tests assert subdivision rather than
  silent truncation, so the guarantee cannot regress.

The design note at `base.py:162-183` records this verified upstream reality and
why we made both steps uniform.
