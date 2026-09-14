"""Facet scoring and interview capture (build spec sections 9 and 10)."""

from estate_scan.score.interview import load_interview
from estate_scan.score.scorer import score

__all__ = ["score", "load_interview"]
