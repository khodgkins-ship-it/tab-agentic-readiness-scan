"""Report emit (build spec section 11, report web app spec).

Five artifacts from one run: findings.json (the contract), report.md,
variants.xlsx, report.html (two redaction builds), and run.log. The findings
dict assembled here is the single source of truth; every artifact is a
rendering of it, and the web app payload is a documented subset rather than a
parallel format.
"""

from estate_scan.report.emit import emit_all

__all__ = ["emit_all"]
