"""Interview capture loader (build spec section 10).

The primary input path for the prototype: a YAML file the specialist edits,
one block per facet carrying a score, a note, and the source role. Loaded into
`interview_responses`, a second input to the same store, joined at scoring time.
The loader never touches scan-derived tables; the scan always wins at scoring.
"""

import datetime
from typing import Optional

import yaml


def load_interview(store, run_id, path, captured_by="specialist", now=None):
    # type: (object, str, str, str, Optional[str]) -> int
    """Replace this run's interview responses with the contents of `path`.

    Expected shape:

        responses:
          - facet: semantic.consensus
            score: 2
            note: "tie-out fails against finance close"
            source_role: analytics_leader
            source_name: "optional, excluded from presentation build"
            confidence: reported
    """
    with open(path) as fh:
        doc = yaml.safe_load(fh) or {}
    captured_at = now or (datetime.datetime.utcnow().isoformat() + "Z")

    store.clear_interview(run_id)
    responses = doc.get("responses", []) or []
    for r in responses:
        facet = r.get("facet")
        if not facet:
            raise ValueError("interview response missing `facet`: %r" % r)
        store.save_interview_response(
            run_id, facet, r.get("score"), r.get("note", ""),
            r.get("source_role", ""), r.get("source_name", ""),
            captured_at, captured_by, r.get("confidence", "reported"))
    store.commit()
    return len(responses)
