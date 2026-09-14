"""Synthetic estate generator.

Everything downstream needs fixtures, and hand-authoring them does not scale
(build brief M1). This package builds three synthetic estates deterministically
from a seed and writes each as a normalized `estate.json` plus an
expected-results `manifest.json`.

Two hard rules the generator upholds:

  * The manifest is *measured* from the generated estate, not hand-asserted, so
    it can never silently disagree with the fixture. Generation then asserts the
    build brief's required properties against that measurement and fails loudly
    if the estate drifts from spec.

  * Ground-truth keys are prefixed with `_` (e.g. `_concept`, `_view_count`).
    They exist so the generator can measure the estate and so tests can assert.
    The derivation pipeline must REDISCOVER concepts, dominance and depth from
    names and formulas alone -- the fixture client strips every `_`-prefixed key
    before it ever reaches the pipeline (clients/fixture.py), so the pipeline
    literally cannot read the answer key.
"""
