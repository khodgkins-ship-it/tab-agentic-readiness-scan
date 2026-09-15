"""emit_all -- write the five report artifacts for a run.

Artifacts (report web app spec section 1, build brief M7):
  findings.json              the contract, full detail, one source of truth
  report.md                  the human-readable report
  variants.xlsx              working-detail workbook
  report.presentation.html   web app, circulating build (no formula text)
  report.working.html        web app, working build (formula text + owners)
  run.log                    appended with which builds were produced

Two builds from one run. The pre-emit secret scan runs on BOTH builds before
anything is written; a hit aborts the whole emit rather than writing a leaking
artifact. The console output (and the returned primary) names the presentation
build by default, since that is the one that circulates.
"""

import datetime
import json
import os
from typing import List, Optional

from estate_scan.report.findings import build_findings
from estate_scan.report.markdown import render_markdown
from estate_scan.report.redact import (assert_no_secrets, mark_working, redact)
from estate_scan.report.webapp import render_html
from estate_scan.report.xlsx import write_variants_xlsx

FINDINGS_JSON = "findings.json"
REPORT_MD = "report.md"
VARIANTS_XLSX = "variants.xlsx"
HTML_PRESENTATION = "report.presentation.html"
HTML_WORKING = "report.working.html"
LOG_NAME = "run.log"


def emit_all(store, run_id, out_dir, build="presentation", framing="full"):
    # type: (object, str, str, str, str) -> List[str]
    """Emit every artifact for `run_id` into `out_dir`. Returns the written
    paths, presentation build first when `build` is 'presentation'.

    `framing` selects the report register (report web app spec section 8):
    'full' shows the stage/readiness/score framing; 'light' presents the same
    findings, coverage, and remediation with no stage or score language, for
    accounts that reject a maturity ladder. It is one render flag on one
    payload -- both builds and both HTML files carry it -- not a second
    pipeline; redaction and the secret scan are unchanged.
    """
    if build not in ("presentation", "working"):
        raise ValueError("build must be 'presentation' or 'working', got %r" % build)
    if framing not in ("full", "light"):
        raise ValueError("framing must be 'full' or 'light', got %r" % framing)

    findings = build_findings(store, run_id)
    # Stamp the framing into meta BEFORE the builds branch, so both the working
    # and presentation copies (and every artifact derived from them) carry it.
    findings["meta"]["framing"] = framing
    working = mark_working(findings)
    presentation = redact(findings)

    # Pre-emit secret scan on BOTH builds. Fail before writing anything.
    assert_no_secrets(working, "working")
    assert_no_secrets(presentation, "presentation")

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    selected = presentation if build == "presentation" else working

    paths = []  # type: List[str]

    # findings.json: the contract, full detail (working). Single source of truth.
    p = os.path.join(out_dir, FINDINGS_JSON)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(working, fh, indent=2, sort_keys=True)
    paths.append(p)

    # report.md: rendered from the selected build (presentation by default).
    p = os.path.join(out_dir, REPORT_MD)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(selected))
    paths.append(p)

    # variants.xlsx: working detail (carries formulas and owners).
    p = os.path.join(out_dir, VARIANTS_XLSX)
    write_variants_xlsx(working, p)
    paths.append(p)

    # Both web app builds, always.
    p_present = os.path.join(out_dir, HTML_PRESENTATION)
    with open(p_present, "w", encoding="utf-8") as fh:
        fh.write(render_html(presentation))
    p_working = os.path.join(out_dir, HTML_WORKING)
    with open(p_working, "w", encoding="utf-8") as fh:
        fh.write(render_html(working))

    # Order the two HTML builds so the one the console names comes first.
    if build == "presentation":
        paths.extend([p_present, p_working])
    else:
        paths.extend([p_working, p_present])

    _log(out_dir, run_id, build, framing, paths)
    return paths


def _log(out_dir, run_id, build, framing, paths):
    # type: (str, str, str, str, List[str]) -> None
    now = datetime.datetime.utcnow().isoformat() + "Z"
    line = ("[%s] report emit run=%s primary=%s framing=%s "
            "builds=working,presentation artifacts=%s\n"
            % (now, run_id, build, framing,
               ",".join(os.path.basename(p) for p in paths)))
    with open(os.path.join(out_dir, LOG_NAME), "a", encoding="utf-8") as fh:
        fh.write(line)
