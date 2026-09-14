"""Derivation: formula resolution, normalization, concept grouping, ranking.

These modules read the normalized store (populated by extract) and write the
derived tables (resolved_formulas, metric_groups, metric_variants). They never
touch the API and never read the fixture's ground-truth keys; everything is
rediscovered from field names and formula text.
"""
