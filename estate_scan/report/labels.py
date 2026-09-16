"""Human labels for the internal facet / flag / dimension codes.

Every output asset (markdown report, web app payload, and anything downstream)
renders the *name* and *description* from here, never the raw code. A consumer
of the report has no reason to know what "SEM-03" or "semantic.describability"
means, so those identifiers stay internal: they remain the join keys in
`findings.json` (a facet's `id`, a flag's `id`, a domain's binding-constraint
list) but no visible string is ever a bare code.

This is a presentation catalog, deliberately separate from `flags/rules.yaml`:
rules.yaml is where the field team tunes *firing and scoring*, this is editorial
copy for the reader. It mirrors the existing presentation maps that already live
in the report layer (`markdown._MECH_LABEL`, `markdown._STAGE_NAMES`). The web
app reads these names through the embedded payload (webapp.py copies them in),
so there is one source of truth and no duplicated map in JavaScript.

Descriptions are written to avoid the maturity-ladder vocabulary the
framing-light build forbids (no "stage"/"readiness"/"maturity" language).
"""


# Assessment dimensions (the seven top-level lenses). Names are plain title
# case; the code (e.g. "action_surface") is never shown.
DIMENSION_LABELS = {
    "semantic": "Semantic",
    "data": "Data",
    "governance": "Governance",
    "adoption": "Adoption",
    "action_surface": "Action surface",
    "operating_model": "Operating model",
    "value": "Value",
}


# Facets: the scored/observed sub-lenses of each dimension. Keyed by the dotted
# facet id used internally (including the governance arcs, which surface as
# `governance.<arc>`). name = short label; description = one plain sentence.
FACET_LABELS = {
    "semantic.singularity": {
        "name": "Metric singularity",
        "description": "Whether each core metric has one agreed definition "
                       "rather than competing variants.",
    },
    "semantic.describability": {
        "name": "Metric describability",
        "description": "Whether fields carry descriptions, so their meaning is "
                       "documented rather than tacit.",
    },
    "semantic.exposure_shape": {
        "name": "Data-source exposure shape",
        "description": "Whether analysis draws on governed published data "
                       "sources rather than embedded one-off extracts.",
    },
    "semantic.consensus": {
        "name": "Definition consensus",
        "description": "Whether stakeholders have ratified shared metric "
                       "definitions.",
    },
    "semantic.lifecycle": {
        "name": "Semantic lifecycle",
        "description": "Whether changes to business rules follow a managed "
                       "lifecycle rather than ad-hoc edits.",
    },
    "adoption.reach": {
        "name": "Adoption reach",
        "description": "The share of published content that is actually used.",
    },
    "adoption.decision_culture": {
        "name": "Decision culture",
        "description": "Whether decisions are routinely made from the analytics "
                       "rather than around them.",
    },
    "data.entitlement_at_source": {
        "name": "Entitlement at source",
        "description": "Whether row-level access is enforced in the data source "
                       "rather than in view-layer formulas.",
    },
    "data.provenance": {
        "name": "Data provenance",
        "description": "Whether published data traces cleanly to governed "
                       "upstream sources.",
    },
    "data.freshness": {
        "name": "Data freshness",
        "description": "Whether extracts and refreshes keep data current and "
                       "reliable.",
    },
    "data.retained_grain": {
        "name": "Retained grain",
        "description": "Whether custom SQL preserves the detail needed for "
                       "correct aggregation downstream.",
    },
    "data.integrity": {
        "name": "Data-integrity signals",
        "description": "Whether data-quality warnings are in use to flag "
                       "integrity issues.",
    },
    "action.reversibility": {
        "name": "Action reversibility",
        "description": "Whether automated actions taken on analytics can be "
                       "reviewed and reversed.",
    },
    "operating.ownership": {
        "name": "Operating ownership",
        "description": "Whether analytics assets have clear, accountable owners "
                       "in the operating model.",
    },
    "value.attribution": {
        "name": "Value attribution",
        "description": "Whether business value is attributed back to analytics "
                       "investments.",
    },
    "governance.accountability": {
        "name": "Ownership accountability",
        "description": "The share of data sources with a named, accountable "
                       "owner.",
    },
    "governance.assurance": {
        "name": "Certification assurance",
        "description": "The share of data sources certified as trusted.",
    },
    "governance.preventive": {
        "name": "Preventive controls",
        "description": "Whether access is scoped and restricted before problems "
                       "occur.",
    },
    "governance.detective": {
        "name": "Detective controls",
        "description": "Whether monitoring catches issues, such as certified "
                       "content that carries a live data-quality warning.",
    },
    "governance.corrective": {
        "name": "Corrective controls",
        "description": "Whether detected problems are actually remediated.",
    },
}


# Flags: the catalog codes from rules.yaml, as the reader should see them.
FLAG_LABELS = {
    "SEC-01": {
        "name": "Access rule buried in a formula",
        "description": "A calculated field enforces row-level access in the "
                       "view layer, which a direct query to the data source "
                       "can bypass.",
    },
    "SEC-02": {
        "name": "Overly broad permission",
        "description": "A sensitive capability (write, delete, or change "
                       "permissions) is granted to an everyone-group rather "
                       "than a scoped, named group.",
    },
    "SEM-01": {
        "name": "Many variants of one metric",
        "description": "A core metric is defined many different ways across the "
                       "estate.",
    },
    "SEM-02": {
        "name": "No agreed metric definition",
        "description": "A core metric has multiple competing definitions in "
                       "active use, with none dominant.",
    },
    "SEM-03": {
        "name": "Undocumented fields",
        "description": "Too few fields carry a description, so meaning is tacit "
                       "rather than documented.",
    },
    "SEM-04": {
        "name": "Oversized data source",
        "description": "A data source exposes an unusually large number of "
                       "fields, making it hard to navigate and govern.",
    },
    "SEM-05": {
        "name": "Inconsistent field descriptions",
        "description": "A field's description differs between the REST and "
                       "Metadata views of the same asset.",
    },
    "DF-01": {
        "name": "Reliance on embedded extracts",
        "description": "Too much analysis draws on embedded one-off extracts "
                       "rather than governed published sources.",
    },
    "DF-02": {
        "name": "Redundant upstream tables",
        "description": "One upstream table feeds many published sources, a "
                       "candidate for consolidation.",
    },
    "DF-03": {
        "name": "Chained published sources",
        "description": "Published sources built on other published sources add "
                       "fragile indirection.",
    },
    "DF-04": {
        "name": "Source without a traceable origin",
        "description": "A published source has no discoverable upstream "
                       "lineage.",
    },
    "DF-05": {
        "name": "Stale data still in use",
        "description": "Content viewed recently is backed by a data source "
                       "whose refresh is failing.",
    },
    "DF-06": {
        "name": "High refresh-failure rate",
        "description": "Scheduled refreshes fail often enough to threaten data "
                       "currency.",
    },
    "DF-07": {
        "name": "Grain loss in custom SQL",
        "description": "Custom SQL aggregates away detail needed for correct "
                       "downstream analysis.",
    },
    "DF-08": {
        "name": "Divergent source columns",
        "description": "Sources sharing a root table expose divergent columns, "
                       "hinting at drift.",
    },
    "GOV-01": {
        "name": "Data source without an owner",
        "description": "A published source has no named, accountable owner.",
    },
    "GOV-02": {
        "name": "No data-quality monitoring",
        "description": "Data-quality warnings are not in use, so integrity "
                       "issues go unflagged.",
    },
    "GOV-03": {
        "name": "Certified but flagged content",
        "description": "Content marked certified nonetheless carries an active "
                       "data-quality warning: the trust and health signals "
                       "disagree.",
    },
    "EST-01": {
        "name": "Unused workbooks",
        "description": "Workbooks drew no views in the window: recoverable "
                       "capacity and retirement candidates.",
    },
    "EST-02": {
        "name": "Many business-rule editors",
        "description": "A wide set of people can edit business rules, raising "
                       "change-control risk.",
    },
    "ADO-01": {
        "name": "Shallow user adoption",
        "description": "Only a small share of intended users actively engage "
                       "with the content.",
    },
    "ADO-02": {
        "name": "Concentrated viewership",
        "description": "Views concentrate in a few workbooks; the long tail is "
                       "largely unused.",
    },
}


def _humanize(code):
    # type: (str) -> str
    """Last-resort label for a code with no catalog entry: turn the identifier
    into something readable rather than exposing the raw code. A missing entry
    is a gap to fill here, not a code to show the reader."""
    return (code or "").replace(".", " · ").replace("_", " ").strip().capitalize()


def dimension_name(dim):
    # type: (str) -> str
    return DIMENSION_LABELS.get(dim) or _humanize(dim)


def facet_name(facet_id):
    # type: (str) -> str
    entry = FACET_LABELS.get(facet_id)
    return entry["name"] if entry else _humanize(facet_id)


def facet_description(facet_id):
    # type: (str) -> str
    entry = FACET_LABELS.get(facet_id)
    return entry["description"] if entry else ""


def flag_name(flag_id):
    # type: (str) -> str
    entry = FLAG_LABELS.get(flag_id)
    return entry["name"] if entry else _humanize(flag_id)


def flag_description(flag_id):
    # type: (str) -> str
    entry = FLAG_LABELS.get(flag_id)
    return entry["description"] if entry else ""
