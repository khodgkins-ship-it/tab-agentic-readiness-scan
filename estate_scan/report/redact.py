"""Redaction (report web app spec section 6).

Two builds from one run, and redaction is a build-time decision, not a runtime
toggle: a runtime toggle in a shared file protects nothing.

  - working: full detail, including resolved formula text and owner names.
  - presentation: counts, rankings, disagreement figures, metric and source
    names. No formula text, no individual owner names. This is the build that
    circulates, so the redaction is what keeps business logic from leaving with
    it.

Neither build may contain credentials, tokens, or connection strings. The
pre-emit scan here asserts that and FAILS the build on a hit rather than
warning -- a warning in an artifact that is about to be emailed protects
nothing either.
"""

import copy
import json
import re
from typing import List

# A redaction leaves a visible marker rather than a blank, so a reader of the
# presentation build knows the field was removed on purpose, not missing.
REDACTED = "[redacted]"


def redact(findings):
    # type: (dict) -> dict
    """Return a presentation copy of `findings`: formula text and owner names
    removed, everything else intact. The input is not mutated."""
    out = copy.deepcopy(findings)

    dm = out.get("findings", {}).get("definition_multiplicity", {})
    for group in dm.get("groups", []):
        for variant in group.get("variants", []):
            if variant.get("resolved_formula") is not None:
                variant["resolved_formula"] = REDACTED
            if variant.get("owner") is not None:
                variant["owner"] = REDACTED
            # R3: the raw VDS aggregate is a business figure -- redact it from the
            # presentation build; the diff figures (abs/rel/material) stay.
            ex = variant.get("execution")
            if ex and ex.get("value") is not None:
                ex["value"] = REDACTED
        gx = group.get("execution")
        if gx:
            pair = gx.get("most_material_pair")
            if pair:
                for key in ("reference_value", "variant_value"):
                    if pair.get(key) is not None:
                        pair[key] = REDACTED

    sec = out.get("findings", {}).get("security_exposure", {})
    for field in sec.get("fields", []):
        if field.get("formula") is not None:
            field["formula"] = REDACTED
        if field.get("owner") is not None:
            field["owner"] = REDACTED
    for wb in sec.get("affected_workbooks", []):
        if wb.get("owner") is not None:
            wb["owner"] = REDACTED

    out.setdefault("meta", {})["build"] = "presentation"
    return out


def mark_working(findings):
    # type: (dict) -> dict
    """Tag the working build without altering its content."""
    out = copy.deepcopy(findings)
    out.setdefault("meta", {})["build"] = "working"
    return out


# -- pre-emit secret scan ----------------------------------------------------

class SecretLeak(Exception):
    """A build carried something that looks like a credential. Fatal: the emit
    aborts rather than writing the artifact."""


# Secret-shaped JSON keys. Our own findings keys are none of these, so a hit
# means something upstream added a credential-bearing field.
_SECRET_KEY_RE = re.compile(
    r'"(pat|password|passwd|pwd|secret|client_secret|access_token|'
    r'refresh_token|private_key|api_?key|credentials?|x-tableau-auth)"'
    r'\s*:\s*"[^"]+?"', re.IGNORECASE)

# Secret-shaped values that can hide inside an otherwise-legitimate string
# (a connection literal embedded in a formula, an auth header pasted anywhere).
_SECRET_VAL_RES = [
    re.compile(r"X-Tableau-Auth", re.IGNORECASE),
    re.compile(r"(?:password|pwd)\s*=\s*[^;\s\"&]+", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{16,}"),
]


def assert_no_secrets(findings, build_name):
    # type: (dict, str) -> None
    """Raise SecretLeak if the serialized build matches a credential pattern.
    The exception names the pattern and build, never the matched value."""
    blob = json.dumps(findings, sort_keys=True)
    hits = _scan(blob)
    if hits:
        raise SecretLeak(
            "%s build matched credential pattern(s): %s -- emit aborted"
            % (build_name, ", ".join(sorted(set(hits)))))


def _scan(blob):
    # type: (str) -> List[str]
    hits = []  # type: List[str]
    if _SECRET_KEY_RE.search(blob):
        hits.append("secret-shaped key")
    for rx in _SECRET_VAL_RES:
        if rx.search(blob):
            hits.append(rx.pattern)
    return hits
