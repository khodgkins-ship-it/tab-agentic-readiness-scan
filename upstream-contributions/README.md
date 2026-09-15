# Upstream contributions — prepared, not opened

Three pieces of this build belong upstream in
[`tableau/tableau-metadata-explorer`](https://github.com/tableau/tableau-metadata-explorer)
(Apache-2.0, © Salesforce, Inc.) rather than in our layer, because they improve
the shared tool for every consumer rather than encoding our maturity-framework
point of view (`05-metadata-explorer-reuse.md §8`, `06-build-brief.md §2`):

1. **[Uniform partial-response handling](01-partial-response-detection.md)** — a
   correctness fix. Upstream *detects* node-/time-limit partials but does not act
   on them uniformly; some paths silently forward truncated data and one path
   hard-fails on a warning that carries usable data.
2. **[Server support in the client layer](02-server-support.md)** — API-version
   negotiation instead of a pinned `3.28`, plus capability-gated degradation for
   the Cloud-only usage source so a Server site never reads as silently clean.
3. **[User-context function scan](03-user-context-function-scan.md)** — a
   governance analysis (which calc fields bake access rules into the view layer
   via `USERNAME()`/`ISMEMBEROF()`/…) that any admin would want and that fits
   their governance dashboard naturally.

## Status: NOT opened. Do not open a PR without explicit approval.

Plan invariant 10 (`wiggly-mixing-noodle.md`) and `06-build-brief.md §2` both
say: *contribution candidates are prepared as notes/patches only; PRs only on
explicit approval.* These notes are that preparation. Nothing here has been
pushed, forked, or submitted.

## What these notes are, and are not

Each note is grounded in the **R0 source read** (`R0-FINDINGS.md`), where the
upstream repo was cloned and the relevant files
(`app/proxy/tableau_metadata.py`, `tableau_rest.py`, `admin_insights.py`,
`governance.py`, `router.py`, `host_validator.py`, `query_validator.py`) were
read directly. Each note names the exact upstream file and function it touches,
states the problem, gives an **illustrative** unified diff, describes the test
that would prove it, and cross-references the shipping implementation in *this*
repo that already embodies the fix (so a reviewer can see it working before it
lands upstream).

The diffs are **illustrative, not apply-ready**. They express the change against
the structure R0 recorded; exact line numbers, surrounding context, and import
paths must be **re-derived against a fresh clone of upstream `main`** before
submission, because upstream may have moved since R0 and we did not pin a commit.
Producing apply-ready `.patch` files is a deliberate follow-up (see below) rather
than something done speculatively here.

## To finalize for submission (only on approval)

1. Clone upstream `main`, note the commit SHA, and re-locate each named function.
2. Re-apply each change against the current source; run upstream's own tests.
3. Regenerate each diff as a real `git format-patch` file next to its note.
4. Confirm the contribution is genuinely absent/needed upstream at that SHA
   (upstream may have fixed it in the interim — for #1 especially, re-verify).
5. Open PRs **only** after the user says so, one focused PR per contribution.

## Licensing

These are contributions *back* to the project we vendored `query_validator.py`
from (see `estate_scan/vendor/NOTICE`). They carry no new license terms; on
submission they fall under the project's Apache-2.0 CLA/inbound=outbound terms
like any other contribution.
