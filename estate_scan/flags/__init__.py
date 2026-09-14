"""Declarative flag engine (build spec section 8).

Flags are the output. They are kept declarative in `rules.yaml` -- id, severity,
confidence, facet, rule, threshold, suppression -- so the field team tunes
firing without a code change, and separate from extraction so the same rules run
against any store. `engine.py` evaluates the store and writes the `flags` table.
"""

from estate_scan.flags.engine import evaluate_flags, load_rules

__all__ = ["evaluate_flags", "load_rules"]
