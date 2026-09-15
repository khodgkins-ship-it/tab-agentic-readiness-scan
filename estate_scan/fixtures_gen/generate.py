"""Build the three synthetic estates and their expected-results manifests.

Public entry points:

    build(profile, seed=None) -> (estate_dict, manifest_dict)
    write_fixture(profile, out_dir, seed=None)

`profile` is one of "median", "small", "hostile".

The manifest is measured from the estate by `measure()`, then `build()` asserts
the build brief's required properties against that measurement. If an estate
drifts from spec, generation raises rather than writing a wrong fixture.
"""

import datetime
import json
import os
import random
import re
from typing import Dict, List, Optional, Tuple

from estate_scan import TOOL_VERSION
from estate_scan.queries import query_set_version

# ---------------------------------------------------------------------------
# Profile seeds (fixed so fixtures are reproducible byte-for-byte).
# ---------------------------------------------------------------------------
SEEDS = {"median": 42, "small": 7, "hostile": 1301}

# User-context functions that trip SEC-01 (spec 03 §8).
USER_CONTEXT_FUNCS = ["USERNAME", "ISMEMBEROF", "FULLNAME", "USERDOMAIN"]

_UC_RE = re.compile(r"\b(" + "|".join(USER_CONTEXT_FUNCS) + r")\s*\(", re.IGNORECASE)

# R2 fixtures ---------------------------------------------------------------
# Fixed reference date so usage/refresh timestamps are byte-reproducible (never
# datetime.today()). All R2 dates are derived relative to this.
_REFERENCE_DATE = datetime.date(2025, 9, 1)

# Custom-SQL grain signals. These MIRROR the loader's regexes
# (estate_scan/store/load.py `_SQL_GROUP_BY_RE` / `_SQL_USER_FUNC_RE`) so the
# manifest's ground-truth counts match what the loader records; an acceptance
# test cross-checks the two, catching any drift.
_SQL_GROUP_BY_RE = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
_SQL_USER_FUNC_RE = re.compile(
    r"\b(?:CURRENT_USER|SESSION_USER|SYSTEM_USER)\b|\b(?:USER|USERNAME)\s*\(",
    re.IGNORECASE)

# Hand-written SQL shapes: plain, grain-changing (GROUP BY), and row-level
# security baked into SQL (a user-context function). DF-07 needs all three.
_CUSTOM_SQL_TEMPLATES = [
    "SELECT order_id, amount FROM warehouse.public.fact_sales",
    "SELECT region, SUM(amount) AS total FROM fact_sales GROUP BY region",
    "SELECT * FROM orders WHERE created_by = CURRENT_USER",
    "SELECT customer_id, COUNT(*) AS n FROM events GROUP BY customer_id",
    "SELECT * FROM ledger WHERE owner = USER()",
    "SELECT id, name, status FROM dim_customer",
]

# Rich column set for variant-hosting data sources; formulas below reference
# only these. Filler sources get a smaller generic set to keep the JSON small.
RICH_COLUMNS = [
    "Sales", "Amount", "Cost", "Quantity", "Customer ID", "Order ID",
    "Refunds", "FX Rate", "Adjustments", "Discount", "Last Order Date",
    "Active", "Status", "Orders", "Revenue", "Churned", "Last Login",
    "Churned Customers", "Region", "Email", "Region Owner", "Shipping",
]
GENERIC_COLUMNS = ["Sales", "Amount", "Quantity", "Region", "Customer ID", "Order ID"]


# ---------------------------------------------------------------------------
# Deterministic id / luid minting.
# ---------------------------------------------------------------------------
class _Ids(object):
    def __init__(self):
        self._n = {}

    def _next(self, kind):
        # type: (str) -> int
        self._n[kind] = self._n.get(kind, 0) + 1
        return self._n[kind]

    def luid(self, kind):
        # type: (str) -> str
        i = self._next("luid")
        return "%08x-0000-4000-8000-%012x" % (hash(kind) & 0xFFFFFFFF, i)

    def dsid(self):
        return "ds_%04d" % self._next("ds")

    def wbid(self):
        return "wb_%04d" % self._next("wb")

    def fldid(self):
        return "fld_%05d" % self._next("fld")

    def prjid(self):
        return "prj_%02d" % self._next("prj")


# ---------------------------------------------------------------------------
# Concept catalog for the median fixture.
#
# Each concept lists variant (name, formula) pairs. Formulas are written so the
# derivation pipeline can rediscover the grouping from names + resolved formulas
# alone (shared tokens, shared base columns). `_definition_id` tags materially
# distinct definitions so "9 disagreeing" is measurable.
# ---------------------------------------------------------------------------

def _revenue_variants():
    # type: () -> List[dict]
    """47 revenue variants. Four differently-named (Revenue / Total Revenue /
    Net Rev / Rev USD) must land in one group. A four-member nested chain gives
    depths 1-4. All share the [Sales]/[Amount] base so grouping recovers them.
    """
    out = []  # type: List[dict]
    # The nested chain (lives together in one data source; depths 1..4).
    out.append({"name": "Rev Base", "formula": "SUM([Sales])",
                "chain": True, "refs": [], "def": "rev_base"})
    out.append({"name": "Rev Net", "formula": "[Rev Base] - SUM([Refunds])",
                "chain": True, "refs": ["Rev Base"], "def": "rev_net"})
    out.append({"name": "Rev Net FX", "formula": "[Rev Net] * [FX Rate]",
                "chain": True, "refs": ["Rev Net"], "def": "rev_net_fx"})
    out.append({"name": "Rev Net FX Adj", "formula": "[Rev Net FX] + SUM([Adjustments])",
                "chain": True, "refs": ["Rev Net FX"], "def": "rev_net_fx_adj"})
    # The four differently-named variants.
    out.append({"name": "Revenue", "formula": "SUM([Sales])", "def": "rev_sum_sales"})
    out.append({"name": "Total Revenue", "formula": "SUM([Sales]) + SUM([Shipping])",
                "def": "rev_plus_ship"})
    out.append({"name": "Net Rev", "formula": "SUM([Sales]) - SUM([Discount])",
                "def": "rev_less_disc"})
    out.append({"name": "Rev USD", "formula": "SUM([Sales]) * [FX Rate]", "def": "rev_fx"})
    # Flat fillers to reach 47, revenue-tokened, mostly re-using a few defs so
    # the group has realistic duplicate logic under different names.
    filler_formulas = [
        "SUM([Sales])", "SUM( [Sales] )", "SUM([Amount])",
        "SUM([Sales]) - SUM([Refunds])", "SUM([Sales]) * 1.0",
        "SUM([Sales]) + SUM([Adjustments])", "SUM([Amount]) - SUM([Discount])",
    ]
    i = 0
    while len(out) < 47:
        f = filler_formulas[i % len(filler_formulas)]
        out.append({"name": "Revenue %02d" % (i + 1), "formula": f,
                    "def": "flat_%d" % (i % len(filler_formulas))})
        i += 1
    return out


def _active_customer_variants():
    # type: () -> List[dict]
    """14 variants, 9 materially distinct definitions (`def`), 5 duplicates.
    The 30-day vs 90-day pair demonstrates that a date boundary is preserved by
    normalization (M3 acceptance)."""
    distinct = [
        ("Active Customers", "COUNTD([Customer ID])", "all_custs"),
        ("Active Flag Customers", "COUNTD(IF [Active] THEN [Customer ID] END)", "flag"),
        ("Customers Active 30d",
         "COUNTD(IF [Last Order Date] > TODAY() - 30 THEN [Customer ID] END)", "d30"),
        ("Customers Active 90d",
         "COUNTD(IF [Last Order Date] > TODAY() - 90 THEN [Customer ID] END)", "d90"),
        ("Status Active Customers",
         "COUNTD(IF [Status] = 'active' THEN [Customer ID] END)", "status"),
        ("Ordering Customers",
         "COUNTD(IF [Orders] > 0 THEN [Customer ID] END)", "orders"),
        ("Revenue Customers",
         "COUNTD(IF [Revenue] > 0 THEN [Customer ID] END)", "revpos"),
        ("Non-Churned Customers",
         "COUNTD(IF [Churned] = FALSE THEN [Customer ID] END)", "notchurn"),
        ("Logged-in Customers",
         "COUNTD(IF [Last Login] > TODAY() - 30 THEN [Customer ID] END)", "login"),
    ]
    dups = [
        ("Active Customer Count", "COUNTD( [Customer ID] )", "all_custs"),
        ("Active Cust", "COUNTD([Customer ID])", "all_custs"),
        ("Active Customer (flag)", "COUNTD(IF [Active] THEN [Customer ID] END)", "flag"),
        ("30d Active Customers",
         "COUNTD(IF [Last Order Date] > TODAY() - 30 THEN [Customer ID] END)", "d30"),
        ("Active Status Cust",
         "COUNTD(IF [Status] = 'active' THEN [Customer ID] END)", "status"),
    ]
    out = []
    for name, formula, d in distinct + dups:
        out.append({"name": name, "formula": formula, "def": d})
    return out


def _simple_group(names, formulas, defs):
    # type: (List[str], List[str], List[str]) -> List[dict]
    out = []
    for i, name in enumerate(names):
        out.append({"name": name, "formula": formulas[i % len(formulas)],
                    "def": defs[i % len(defs)]})
    return out


def _gross_margin_variants():
    names = ["Gross Margin", "GM %", "Gross Margin Pct", "Margin", "GM",
             "Gross Margin Rate", "Contribution Margin", "Gross Profit Margin"]
    formulas = [
        "(SUM([Sales]) - SUM([Cost])) / SUM([Sales])",
        "1 - SUM([Cost]) / SUM([Sales])",
        "(SUM([Amount]) - SUM([Cost])) / SUM([Amount])",
    ]
    defs = ["gm_a", "gm_b", "gm_c"]
    return _simple_group(names, formulas, defs)


def _churn_variants():
    names = ["Churn Rate", "Churn %", "Customer Churn", "Churn",
             "Monthly Churn", "Logo Churn"]
    formulas = [
        "COUNTD([Churned Customers]) / COUNTD([Customer ID])",
        "COUNTD(IF [Churned] THEN [Customer ID] END) / COUNTD([Customer ID])",
    ]
    defs = ["churn_a", "churn_b"]
    return _simple_group(names, formulas, defs)


def _aov_variants():
    names = ["Average Order Value", "AOV", "Avg Order Value", "Order Value Avg",
             "Mean Order Value", "AOV USD", "Avg Basket"]
    formulas = [
        "SUM([Sales]) / COUNTD([Order ID])",
        "SUM([Amount]) / COUNTD([Order ID])",
    ]
    defs = ["aov_a", "aov_b"]
    return _simple_group(names, formulas, defs)


# View-count distributions per group, rank-ordered (index 0 = rank 1).
GROUP_VIEWS = {
    "revenue": [6200, 1100, 900] + [41] * 40 + [40] * 4,      # 47, dominant, cover80=3
    "active_customer": [3000, 2200, 1500, 1200, 900, 800, 700,
                        600, 500, 400, 300, 200, 100, 100],    # 14, no dominant
    "gross_margin": [1000, 900, 800, 700, 600, 500, 400, 300],  # 8
    "churn_rate": [1000, 800, 700, 600, 500, 400],              # 6
    "average_order_value": [1200, 1000, 800, 600, 500, 400, 300],  # 7
}

CORE_METRICS = ["revenue", "active_customer", "gross_margin",
                "churn_rate", "average_order_value"]

GROUP_BUILDERS = {
    "revenue": _revenue_variants,
    "active_customer": _active_customer_variants,
    "gross_margin": _gross_margin_variants,
    "churn_rate": _churn_variants,
    "average_order_value": _aov_variants,
}


# ---------------------------------------------------------------------------
# Field / datasource / workbook construction helpers.
# ---------------------------------------------------------------------------

def _mk_column(ids, name, described):
    # type: (_Ids, str, bool) -> dict
    return {
        "__typename": "ColumnField",
        "id": ids.fldid(),
        "name": name,
        "description": ("Source column %s." % name) if described else "",
        "isHidden": False,
        "dataType": "REAL" if name in ("Sales", "Amount", "Cost") else "STRING",
        "role": "MEASURE" if name in ("Sales", "Amount", "Cost", "Quantity") else "DIMENSION",
        "formula": None,
        "_is_calculated": False,
        "_concept": None,
        "_is_metric_variant": False,
        "_definition_id": None,
        "_ref_field_ids": [],
        "_view_count": 0,
        "_used_in_workbooks": [],
    }


def _mk_calc(ids, name, formula, described, concept=None, is_variant=False,
             definition_id=None):
    # type: (_Ids, str, str, bool, Optional[str], bool, Optional[str]) -> dict
    return {
        "__typename": "CalculatedField",
        "id": ids.fldid(),
        "name": name,
        "description": ("Calculated field %s." % name) if described else "",
        "isHidden": False,
        "dataType": "REAL",
        "role": "MEASURE",
        "formula": formula,
        "_is_calculated": True,
        "_concept": concept,
        "_is_metric_variant": is_variant,
        "_definition_id": definition_id,
        "_ref_field_ids": [],          # ground-truth adjacency, filled after mint
        "_view_count": 0,
        "_used_in_workbooks": [],
    }


def _mk_datasource(ids, name, project, rng, rich=False, described_prob=0.55,
                   upstream_tables=None, upstream_ds_ids=None, certified=None):
    # type: (_Ids, str, str, random.Random, bool, float, Optional[list], Optional[list], Optional[bool]) -> dict
    cols = RICH_COLUMNS if rich else GENERIC_COLUMNS
    fields = [_mk_column(ids, c, rng.random() < described_prob) for c in cols]
    is_cert = rng.random() < 0.3 if certified is None else certified
    return {
        "id": ids.dsid(),
        "luid": ids.luid("ds"),
        "name": name,
        "projectName": project,
        "isCertified": is_cert,
        "certificationNote": "Reviewed by data team." if is_cert else "",
        "owner": {"username": "svc_etl" if rng.random() < 0.1 else ("user%d" % rng.randint(1, 40)),
                  "email": ""},
        "hasExtracts": rng.random() < 0.5,
        "upstreamTables": upstream_tables if upstream_tables is not None else [
            {"id": ids.luid("tbl"), "name": "t_%s" % name.lower().replace(" ", "_"),
             "schema": "public", "fullName": "warehouse.public.t_%d" % rng.randint(1, 500)}
        ],
        "upstreamDatasources": upstream_ds_ids or [],
        "fields": fields,
        "_described_prob": described_prob,
    }


def _add_calc_to_ds(ds, calc):
    # type: (dict, dict) -> None
    ds["fields"].append(calc)


def _resolve_refs_in_ds(ds):
    # type: (dict) -> None
    """Fill each calc field's ground-truth `_ref_field_ids` by matching bracketed
    names against other fields in the SAME data source (resolution is scoped to
    the containing source, spec 03 §7.1)."""
    by_name = {}
    for f in ds["fields"]:
        by_name[f["name"].lower()] = f["id"]
    ref_re = re.compile(r"\[([^\]]+)\]")
    for f in ds["fields"]:
        if not f.get("formula"):
            continue
        refs = []
        for m in ref_re.finditer(f["formula"]):
            target = by_name.get(m.group(1).lower())
            if target and target != f["id"] and target not in refs:
                # only count references to CALCULATED fields for depth
                tgt = next((x for x in ds["fields"] if x["id"] == target), None)
                if tgt and tgt["_is_calculated"]:
                    refs.append(target)
        f["_ref_field_ids"] = refs


def _mk_workbook(ids, name, project, rng, upstream_ds=None, embedded_ds=None,
                 described_prob=0.55):
    # type: (_Ids, str, str, random.Random, Optional[list], Optional[list], float) -> dict
    return {
        "id": ids.wbid(),
        "luid": ids.luid("wb"),
        "name": name,
        "projectName": project,
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2025-06-01T00:00:00Z",
        "owner": {"username": "user%d" % rng.randint(1, 40), "email": ""},
        "upstreamDatasources": upstream_ds or [],
        "embeddedDatasources": embedded_ds or [],
        "sheets": [{"id": ids.luid("sh"), "name": "%s Sheet" % name}],
        "dashboards": [{"id": ids.luid("db"), "name": "%s Dashboard" % name}],
    }


# ---------------------------------------------------------------------------
# Median fixture.
# ---------------------------------------------------------------------------

def _build_median(seed):
    # type: (int) -> dict
    rng = random.Random(seed)
    ids = _Ids()
    projects = [{"id": ids.prjid(), "name": n, "parentProjectName": None}
                for n in ["Finance", "Sales", "Marketing", "Customer", "Ops",
                          "Exec", "Data Eng", "Product", "Support", "HR"]]
    pnames = [p["name"] for p in projects]

    datasources = []  # type: List[dict]

    # -- DF-02: >10 published sources tracing to one upstream table.
    shared_tbl = {"id": ids.luid("tbl"), "name": "fact_sales", "schema": "public",
                  "fullName": "warehouse.public.fact_sales"}
    for i in range(12):
        datasources.append(_mk_datasource(
            ids, "Sales Extract %02d" % i, "Sales", rng, rich=False,
            upstream_tables=[shared_tbl]))

    # -- DF-03: published-on-published chain, depth 2 (C on B on A).
    ds_a = _mk_datasource(ids, "Base Warehouse DS", "Data Eng", rng, rich=False)
    ds_b = _mk_datasource(ids, "Curated DS", "Data Eng", rng, rich=False,
                          upstream_ds_ids=[{"id": ds_a["id"], "luid": ds_a["luid"], "name": ds_a["name"]}])
    ds_c = _mk_datasource(ids, "Mart DS", "Data Eng", rng, rich=False,
                          upstream_ds_ids=[{"id": ds_b["id"], "luid": ds_b["luid"], "name": ds_b["name"]}])
    datasources += [ds_a, ds_b, ds_c]

    # -- DF-04: sources with no traceable upstream.
    for i in range(3):
        datasources.append(_mk_datasource(
            ids, "Orphan DS %02d" % i, "Ops", rng, rich=False, upstream_tables=[]))

    # -- Finance Core: hosts the revenue nested chain (rich columns).
    finance_core = _mk_datasource(ids, "Finance Core", "Finance", rng, rich=True,
                                  certified=True)
    datasources.append(finance_core)

    # -- Filler datasources up to 200.
    while len(datasources) < 200:
        datasources.append(_mk_datasource(
            ids, "DS %03d" % len(datasources), rng.choice(pnames), rng, rich=False))

    # Rich column set on any datasource that will host a metric variant so the
    # variant formulas resolve. We host variants on a rotating pool that starts
    # with rich sources.
    variant_pool = [finance_core]
    for ds in datasources:
        if ds is finance_core:
            continue
        # upgrade ~80 sources to rich so spread variants resolve
        if len(variant_pool) < 90:
            # ensure rich columns present
            have = set(f["name"] for f in ds["fields"])
            for c in RICH_COLUMNS:
                if c not in have:
                    ds["fields"].append(_mk_column(ids, c, rng.random() < 0.55))
            variant_pool.append(ds)

    # -- Metric variants ----------------------------------------------------
    metric_fields = []  # (concept, field, ds)
    # Revenue chain into Finance Core.
    rev_specs = GROUP_BUILDERS["revenue"]()
    chain_specs = [s for s in rev_specs if s.get("chain")]
    flat_specs = [s for s in rev_specs if not s.get("chain")]
    for s in chain_specs:
        c = _mk_calc(ids, s["name"], s["formula"], rng.random() < 0.55,
                     concept="revenue", is_variant=True, definition_id=s["def"])
        _add_calc_to_ds(finance_core, c)
        metric_fields.append(("revenue", c, finance_core))
    # Flat revenue variants + other groups: spread across variant_pool[1:].
    pool = variant_pool[1:]
    pi = 0
    for s in flat_specs:
        ds = pool[pi % len(pool)]; pi += 1
        c = _mk_calc(ids, s["name"], s["formula"], rng.random() < 0.55,
                     concept="revenue", is_variant=True, definition_id=s["def"])
        _add_calc_to_ds(ds, c)
        metric_fields.append(("revenue", c, ds))
    for concept in ["active_customer", "gross_margin", "churn_rate", "average_order_value"]:
        for s in GROUP_BUILDERS[concept]():
            ds = pool[pi % len(pool)]; pi += 1
            c = _mk_calc(ids, s["name"], s["formula"], rng.random() < 0.55,
                         concept=concept, is_variant=True, definition_id=s["def"])
            _add_calc_to_ds(ds, c)
            metric_fields.append((concept, c, ds))

    # -- SEC-01: 22 user-context calc fields spread across sources.
    uc_templates = [
        ("RLS Region", "IF ISMEMBEROF('Finance') THEN [Sales] ELSE 0 END"),
        ("Owner Filter", "IF [Region Owner] = USERNAME() THEN [Amount] END"),
        ("My Records", "[Email] = USERNAME()"),
        ("Full Name", "FULLNAME()"),
        ("User Domain Flag", "IF USERDOMAIN() = 'CORP' THEN 1 ELSE 0 END"),
        ("Member Sales", "IF ISMEMBEROF('Sales') THEN SUM([Sales]) END"),
    ]
    sec01_count = 0
    for i in range(22):
        name, formula = uc_templates[i % len(uc_templates)]
        ds = pool[(pi + i) % len(pool)]
        c = _mk_calc(ids, "%s %02d" % (name, i), formula, rng.random() < 0.55)
        _add_calc_to_ds(ds, c)
        sec01_count += 1

    # Resolve ground-truth adjacency within each datasource.
    for ds in datasources:
        _resolve_refs_in_ds(ds)

    # -- Workbooks + usage --------------------------------------------------
    ds_by_id = {d["id"]: d for d in datasources}
    workbooks = []  # type: List[dict]
    usage = []  # type: List[dict]

    # One dedicated metric workbook per variant, carrying the variant's views.
    # Assign rank-ordered views within each concept.
    per_concept = {}  # type: Dict[str, List[dict]]
    for concept, fld, ds in metric_fields:
        per_concept.setdefault(concept, []).append((fld, ds))
    for concept, lst in per_concept.items():
        views = GROUP_VIEWS[concept]
        # deterministic order: by field id
        lst_sorted = sorted(lst, key=lambda t: t[0]["id"])
        for rank, (fld, ds) in enumerate(lst_sorted):
            v = views[rank] if rank < len(views) else 1
            wb = _mk_workbook(ids, "%s v%02d" % (concept, rank), ds["projectName"], rng,
                              upstream_ds=[{"id": ds["id"], "luid": ds["luid"], "name": ds["name"]}],
                              embedded_ds=[])
            workbooks.append(wb)
            usage.append({"workbook_id": wb["id"], "workbook_luid": wb["luid"],
                          "views": v, "last_viewed_days_ago": rng.randint(1, 20)})
            fld["_view_count"] = v
            fld["_used_in_workbooks"] = [wb["luid"]]

    # Filler workbooks up to 1000. Distribution shaped for concentration,
    # EST-01 (zeros) and DF-01 (embedded share). Embedded ds ids are synthetic
    # (not published), so they inflate the embedded share without new sources.
    def _emb(n):
        return [{"id": ids.luid("emb"), "name": "Embedded %d" % rng.randint(1, 9999)}
                for _ in range(n)]

    n_zero, n_head, n_mid = 150, 120, 1000 - len(workbooks) - 150 - 120
    for i in range(n_head):
        ds = rng.choice(datasources)
        wb = _mk_workbook(ids, "Head WB %03d" % i, ds["projectName"], rng,
                          upstream_ds=([{"id": ds["id"], "luid": ds["luid"], "name": ds["name"]}]
                                       if rng.random() < 0.3 else []),
                          embedded_ds=_emb(rng.randint(1, 2)))
        workbooks.append(wb)
        usage.append({"workbook_id": wb["id"], "workbook_luid": wb["luid"],
                      "views": rng.randint(500, 3000), "last_viewed_days_ago": rng.randint(1, 30)})
    for i in range(n_mid):
        wb = _mk_workbook(ids, "Mid WB %04d" % i, rng.choice(pnames), rng,
                          upstream_ds=[], embedded_ds=_emb(rng.randint(1, 2)))
        workbooks.append(wb)
        usage.append({"workbook_id": wb["id"], "workbook_luid": wb["luid"],
                      "views": rng.randint(1, 60), "last_viewed_days_ago": rng.randint(1, 89)})
    for i in range(n_zero):
        wb = _mk_workbook(ids, "Stale WB %03d" % i, rng.choice(pnames), rng,
                          upstream_ds=[], embedded_ds=_emb(1))
        workbooks.append(wb)
        usage.append({"workbook_id": wb["id"], "workbook_luid": wb["luid"],
                      "views": 0, "last_viewed_days_ago": None})

    estate = {
        "meta": {
            "profile": "median",
            "seed": seed,
            "tool_version": TOOL_VERSION,
            "query_set_version": query_set_version(),
            "deployment_type": "cloud",
            "adoption_source": "fixture",
            "site": {"luid": ids.luid("site"), "name": "median-site"},
            "core_metrics": CORE_METRICS,
            "domains": [{"id": "revenue_ops", "target_stage": 5,
                         "projects": ["Finance", "Sales", "Customer"]}],
        },
        "projects": projects,
        "datasources": datasources,
        "workbooks": workbooks,
        "usage_events": usage,
    }
    estate["_meta_expected"] = {"sec01_count": sec01_count}
    return estate


# ---------------------------------------------------------------------------
# Small fixture: ~100 workbooks, clean lineage, few variants, no SEM-02/SEC-01.
# ---------------------------------------------------------------------------

def _build_small(seed):
    # type: (int) -> dict
    rng = random.Random(seed)
    ids = _Ids()
    projects = [{"id": ids.prjid(), "name": n, "parentProjectName": None}
                for n in ["Finance", "Sales", "Ops"]]
    pnames = [p["name"] for p in projects]
    datasources = []
    for i in range(20):
        datasources.append(_mk_datasource(ids, "Clean DS %02d" % i,
                                           rng.choice(pnames), rng, rich=True,
                                           described_prob=0.9, certified=True))
    # One variant per core metric (singular, dominant by construction).
    metric_fields = []
    singles = {
        "revenue": ("Revenue", "SUM([Sales])"),
        "active_customer": ("Active Customers", "COUNTD([Customer ID])"),
        "gross_margin": ("Gross Margin", "(SUM([Sales]) - SUM([Cost])) / SUM([Sales])"),
        "churn_rate": ("Churn Rate", "COUNTD([Churned Customers]) / COUNTD([Customer ID])"),
        "average_order_value": ("Average Order Value", "SUM([Sales]) / COUNTD([Order ID])"),
    }
    for idx, (concept, (nm, fm)) in enumerate(singles.items()):
        ds = datasources[idx]
        c = _mk_calc(ids, nm, fm, True, concept=concept, is_variant=True,
                     definition_id=concept + "_only")
        _add_calc_to_ds(ds, c)
        metric_fields.append((concept, c, ds))
    for ds in datasources:
        _resolve_refs_in_ds(ds)

    workbooks, usage = [], []
    for concept, fld, ds in metric_fields:
        wb = _mk_workbook(ids, "%s WB" % concept, ds["projectName"], rng,
                          upstream_ds=[{"id": ds["id"], "luid": ds["luid"], "name": ds["name"]}])
        workbooks.append(wb)
        v = rng.randint(200, 800)
        usage.append({"workbook_id": wb["id"], "workbook_luid": wb["luid"],
                      "views": v, "last_viewed_days_ago": rng.randint(1, 20)})
        fld["_view_count"] = v
        fld["_used_in_workbooks"] = [wb["luid"]]
    while len(workbooks) < 100:
        ds = rng.choice(datasources)
        wb = _mk_workbook(ids, "WB %03d" % len(workbooks), ds["projectName"], rng,
                          upstream_ds=[{"id": ds["id"], "luid": ds["luid"], "name": ds["name"]}])
        workbooks.append(wb)
        usage.append({"workbook_id": wb["id"], "workbook_luid": wb["luid"],
                      "views": rng.randint(5, 300), "last_viewed_days_ago": rng.randint(1, 80)})

    return {
        "meta": {
            "profile": "small", "seed": seed, "tool_version": TOOL_VERSION,
            "query_set_version": query_set_version(), "deployment_type": "cloud",
            "adoption_source": "fixture",
            "site": {"luid": ids.luid("site"), "name": "small-site"},
            "core_metrics": CORE_METRICS,
            "domains": [{"id": "all", "target_stage": 3, "projects": pnames}],
        },
        "projects": projects, "datasources": datasources,
        "workbooks": workbooks, "usage_events": usage,
        "_meta_expected": {"sec01_count": 0},
    }


# ---------------------------------------------------------------------------
# Hostile fixture: small but full of formula-resolution edge cases (M3).
# ---------------------------------------------------------------------------

def _build_hostile(seed):
    # type: (int) -> dict
    rng = random.Random(seed)
    ids = _Ids()
    projects = [{"id": ids.prjid(), "name": "Hostile", "parentProjectName": None}]

    # Data source 1: cycle + deep chains + caption reference.
    ds1 = _mk_datasource(ids, "Edge DS 1", "Hostile", rng, rich=True, certified=False)
    # Cycle A -> B -> A
    ca = _mk_calc(ids, "Cycle A", "[Cycle B] + 1", True)
    cb = _mk_calc(ids, "Cycle B", "[Cycle A] + 2", True)
    ds1["fields"] += [ca, cb]
    # Deep chain of length 14 (exceeds MAX_DEPTH 12 -> TOO_DEEP at the top).
    prev = "SUM([Sales])"
    for i in range(14):
        nm = "Deep %02d" % i
        formula = prev if i == 0 else "[Deep %02d] + 1" % (i - 1)
        ds1["fields"].append(_mk_calc(ids, nm, formula, i % 2 == 0))
    # Chain exactly 4 deep (all RESOLVED).
    ds1["fields"].append(_mk_calc(ids, "Ok 1", "SUM([Amount])", True))
    ds1["fields"].append(_mk_calc(ids, "Ok 2", "[Ok 1] * 2", True))
    ds1["fields"].append(_mk_calc(ids, "Ok 3", "[Ok 2] + [Ok 1]", True))
    ds1["fields"].append(_mk_calc(ids, "Ok 4", "[Ok 3] - 1", True))
    # Unresolved reference (points at a name that does not exist).
    ds1["fields"].append(_mk_calc(ids, "Dangling", "[No Such Field] + 1", True))
    # Unicode field name + a reference to it.
    ds1["fields"].append(_mk_calc(ids, u"Ingresos ñ", "SUM([Sales])", True))
    ds1["fields"].append(_mk_calc(ids, "Uses Unicode", u"[Ingresos ñ] * 1.1", True))

    # Data source 2: NAME COLLISION -- same field name, different formula, must
    # resolve independently because resolution is scoped to the source.
    ds2 = _mk_datasource(ids, "Edge DS 2", "Hostile", rng, rich=True, certified=False)
    ds2["fields"].append(_mk_calc(ids, "Rev Base", "SUM([Amount]) * 2", True))  # collides w/ median name idea
    ds2["fields"].append(_mk_calc(ids, "Uses Rev", "[Rev Base] + 5", True))

    datasources = [ds1, ds2]
    for ds in datasources:
        _resolve_refs_in_ds(ds)

    # Minimal workbooks/usage so the pipeline runs end to end.
    workbooks, usage = [], []
    for i, ds in enumerate(datasources):
        wb = _mk_workbook(ids, "Hostile WB %d" % i, "Hostile", rng,
                          upstream_ds=[{"id": ds["id"], "luid": ds["luid"], "name": ds["name"]}])
        workbooks.append(wb)
        usage.append({"workbook_id": wb["id"], "workbook_luid": wb["luid"],
                      "views": rng.randint(1, 50), "last_viewed_days_ago": rng.randint(1, 80)})

    return {
        "meta": {
            "profile": "hostile", "seed": seed, "tool_version": TOOL_VERSION,
            "query_set_version": query_set_version(), "deployment_type": "cloud",
            "adoption_source": "fixture",
            "site": {"luid": ids.luid("site"), "name": "hostile-site"},
            "core_metrics": [], "domains": [],
        },
        "projects": projects, "datasources": datasources,
        "workbooks": workbooks, "usage_events": usage,
        "_meta_expected": {"sec01_count": 0},
    }


BUILDERS = {"median": _build_median, "small": _build_small, "hostile": _build_hostile}


# ---------------------------------------------------------------------------
# Measurement: compute the expected-results manifest from the estate ground
# truth. This is what later milestones assert their pipeline output against.
# ---------------------------------------------------------------------------

def _cover_k(sorted_desc, total, frac):
    # type: (List[int], int, float) -> int
    if total <= 0:
        return 0
    target = frac * total
    cum, k = 0, 0
    for v in sorted_desc:
        cum += v
        k += 1
        if cum >= target:
            return k
    return k


def _ground_depth(ds):
    # type: (dict) -> Dict[str, int]
    """Ground-truth resolution depth per calc field id, from `_ref_field_ids`.
    depth 1 = references only base columns; a cycle returns -1."""
    by_id = {f["id"]: f for f in ds["fields"]}
    memo = {}  # type: Dict[str, int]

    def depth(fid, seen):
        if fid in seen:
            return -1  # cycle
        if fid in memo:
            return memo[fid]
        f = by_id[fid]
        refs = [r for r in f["_ref_field_ids"] if r in by_id]
        if not refs:
            d = 1
        else:
            child = [depth(r, seen | {fid}) for r in refs]
            if -1 in child:
                d = -1
            else:
                d = 1 + max(child)
        memo[fid] = d
        return d

    return {f["id"]: depth(f["id"], set())
            for f in ds["fields"] if f["_is_calculated"]}


def _enrich_r2(estate, seed):
    # type: (dict, int) -> None
    """R2: add refresh_jobs / custom_sql / permissions and enrich usage_events
    with a per-user identity + event date.

    Runs AFTER the profile builder has fully consumed its own RNG stream, using a
    dedicated Random(seed + offset). This is deliberate: inserting rng calls into
    a builder mid-stream would shift every downstream draw and break the byte-for
    -byte fixtures and `_assert_profile`. Everything here is pure derivation over
    the already-built estate (fixed reference date, estate iteration order), so it
    is uniform across all three profiles and reproducible."""
    rng = random.Random(seed + 90210)
    datasources = estate.get("datasources", [])
    workbooks = estate.get("workbooks", [])
    projects = estate.get("projects", [])

    # -- usage_events: per-user identity + event date -----------------------
    # ADO-01's ceiling: depth is measurable only when an event carries a user.
    # Viewed workbooks attribute to their owner; zero-view rows stay identity-
    # and date-less (last_viewed_days_ago is None there).
    owner_by_wb = {wb["id"]: (wb.get("owner") or {}).get("username")
                   for wb in workbooks}
    for u in estate.get("usage_events", []):
        u["user_id"] = owner_by_wb.get(u.get("workbook_id")) if u.get("views", 0) > 0 else None
        days = u.get("last_viewed_days_ago")
        u["event_date"] = (
            None if days is None
            else (_REFERENCE_DATE - datetime.timedelta(days=int(days))).isoformat())

    # -- refresh_jobs: one per extract-backed source ------------------------
    # Freshness spread (DF-05/06): mostly fresh, some stale, a few failed.
    refresh_jobs = []  # type: List[dict]
    for ds in datasources:
        if not ds.get("hasExtracts"):
            continue
        roll = rng.random()
        if roll < 0.7:
            days_ago, status = rng.randint(0, 2), "Success"
        elif roll < 0.9:
            days_ago, status = rng.randint(10, 60), "Success"   # stale
        else:
            days_ago, status = rng.randint(1, 30), "Failed"
        day = (_REFERENCE_DATE - datetime.timedelta(days=days_ago)).isoformat()
        refresh_jobs.append({
            "task_id": "task_%s" % ds["id"],
            "datasource_id": ds["id"],
            "scheduled_at": day + "T02:00:00Z",
            "completed_at": day + "T02:05:00Z",
            "status": status,
        })
    estate["refresh_jobs"] = refresh_jobs

    # -- custom_sql: hand-written SQL tables --------------------------------
    n_cs = min(2 * len(_CUSTOM_SQL_TEMPLATES), len(datasources)) if datasources else 0
    custom_sql = []  # type: List[dict]
    for i in range(n_cs):
        ds = datasources[i % len(datasources)]
        custom_sql.append({
            "id": "csql_%04d" % (i + 1),
            "name": "Custom SQL %02d" % (i + 1),
            "query": _CUSTOM_SQL_TEMPLATES[i % len(_CUSTOM_SQL_TEMPLATES)],
            "downstreamDatasources": [
                {"id": ds["id"], "luid": ds["luid"], "name": ds["name"]}],
        })
    estate["custom_sql"] = custom_sql

    # -- permissions: project-level (all) + content-level (sampled) ---------
    permissions = []  # type: List[dict]
    for pj in projects:
        for grantee, grant_caps in (("group:AllUsers", ["Read"]),
                                    ("group:Analysts", ["Read", "Write"])):
            gtype, gid = grantee.split(":")
            for cap in grant_caps:
                permissions.append({
                    "object_type": "project", "object_id": pj["id"],
                    "grantee_type": gtype, "grantee_id": gid,
                    "capability": cap, "mode": "Allow", "sampled": 0})
    sample_n = max(1, len(workbooks) // 20) if workbooks else 0
    for wb in workbooks[:sample_n]:
        permissions.append({
            "object_type": "workbook", "object_id": wb["id"],
            "grantee_type": "user",
            "grantee_id": (wb.get("owner") or {}).get("username") or "user0",
            "capability": rng.choice(["Read", "Write", "Delete", "ChangePermissions"]),
            "mode": rng.choice(["Allow", "Deny"]),
            "sampled": 1})
    estate["permissions"] = permissions


def measure(estate):
    # type: (dict) -> dict
    dss = estate["datasources"]
    all_fields = [f for ds in dss for f in ds["fields"]]
    calc_fields = [f for f in all_fields if f["_is_calculated"]]

    # metric groups
    groups = {}  # type: Dict[str, dict]
    variants_by_concept = {}  # type: Dict[str, List[dict]]
    for f in all_fields:
        if f.get("_is_metric_variant"):
            variants_by_concept.setdefault(f["_concept"], []).append(f)
    for concept, variants in variants_by_concept.items():
        views = sorted((v["_view_count"] for v in variants), reverse=True)
        total = sum(views)
        rank1 = views[0] if views else 0
        rank2 = views[1] if len(views) > 1 else 0
        dominant = bool(views) and rank1 >= 0.6 * total and (
            len(views) == 1 or rank1 >= 2 * rank2)
        distinct_defs = len(set(v["_definition_id"] for v in variants))
        usage_variants = sum(1 for v in variants if v["_view_count"] > 0)
        groups[concept] = {
            "variants": len(variants),
            "variants_covering_80pct_views": _cover_k(views, total, 0.8),
            "group_views": total,
            "dominant": dominant,
            "distinct_definitions": distinct_defs,
            "disagreeing_variants": distinct_defs,
            "variants_with_usage": usage_variants,
            "fires_sem01": len(variants) > 5,
            "fires_sem02": (not dominant) and usage_variants >= 2,
        }

    core = estate["meta"].get("core_metrics", [])
    core_present = [c for c in core if c in groups]
    dom_share = (sum(1 for c in core_present if groups[c]["dominant"]) / len(core_present)
                 if core_present else 0.0)

    # user-context fields (SEC-01)
    uc = sum(1 for f in calc_fields if f.get("formula") and _UC_RE.search(f["formula"]))

    # nested depth (ground truth), ignoring cycles for the max
    max_depth = 0
    depth_hist = {}  # type: Dict[int, int]
    for ds in dss:
        for fid, d in _ground_depth(ds).items():
            depth_hist[d] = depth_hist.get(d, 0) + 1
            if d > max_depth:
                max_depth = d

    # description coverage
    described = sum(1 for f in all_fields if (f.get("description") or "").strip())
    coverage = described / len(all_fields) if all_fields else 0.0

    # workbook view concentration
    views_by_wb = sorted((u["views"] for u in estate["usage_events"]), reverse=True)
    total_views = sum(views_by_wb)
    zero_view = sum(1 for u in estate["usage_events"] if u["views"] == 0)

    # embedded share (DF-01): embedded refs / (embedded + published refs)
    emb = sum(len(w["embeddedDatasources"]) for w in estate["workbooks"])
    pub = sum(len(w["upstreamDatasources"]) for w in estate["workbooks"])
    emb_share = emb / (emb + pub) if (emb + pub) else 0.0

    # DF-02: max published sources sharing one upstream table
    tbl_counts = {}  # type: Dict[str, int]
    for ds in dss:
        for t in ds.get("upstreamTables", []):
            key = t.get("fullName") or t.get("name")
            tbl_counts[key] = tbl_counts.get(key, 0) + 1
    max_sources_per_table = max(tbl_counts.values()) if tbl_counts else 0

    # DF-03: max published-on-published depth
    ds_by_id = {d["id"]: d for d in dss}

    def ds_depth(dsid, seen):
        d = ds_by_id.get(dsid)
        if not d or not d.get("upstreamDatasources"):
            return 0
        best = 0
        for up in d["upstreamDatasources"]:
            if up["id"] in seen:
                continue
            best = max(best, 1 + ds_depth(up["id"], seen | {dsid}))
        return best
    max_ds_depth = max((ds_depth(d["id"], set()) for d in dss), default=0)

    # DF-04: sources with no upstream at all
    no_upstream = sum(1 for d in dss
                      if not d.get("upstreamTables") and not d.get("upstreamDatasources"))

    # SEM-04: widest source by field count
    max_fields = max((len(d["fields"]) for d in dss), default=0)

    # GOV-01: published sources with no owner username
    missing_owner = sum(1 for d in dss if not (d.get("owner") or {}).get("username"))

    # SEC-02: permissive grants (Allow of a sensitive capability to an "everyone"
    # group). Computed here exactly as the store evaluator does, so flags_expected
    # agrees with firing without tuning the threshold to the fixture.
    perms = estate.get("permissions", [])
    _EVERYONE = {"AllUsers"}
    _SENSITIVE = {"Write", "Delete", "ChangePermissions", "ProjectLeader"}
    sec02 = sum(1 for p in perms
                if p.get("mode") == "Allow"
                and p.get("grantee_id") in _EVERYONE
                and p.get("capability") in _SENSITIVE)

    # DF-05: a source whose LATEST refresh failed while a published workbook built
    # on it was viewed within the window. Mirrors store.failed_source_recent_views
    # + the evaluator's 30-day filter, so the fixture ground truth and the loaded
    # store agree. One refresh row per source here, so latest == that row.
    rj = estate.get("refresh_jobs", [])
    latest_by_ds = {}  # type: Dict[str, dict]
    for j in rj:
        d = j.get("datasource_id")
        cur = latest_by_ds.get(d)
        if cur is None or (j.get("completed_at") or "") > (cur.get("completed_at") or ""):
            latest_by_ds[d] = j
    failed_sources = {d for d, j in latest_by_ds.items() if j.get("status") == "Failed"}
    wb_last_viewed = {u["workbook_id"]: u.get("last_viewed_days_ago")
                      for u in estate["usage_events"]
                      if u.get("last_viewed_days_ago") is not None}
    pub_wbs_by_ds = {}  # type: Dict[str, set]
    for w in estate["workbooks"]:
        for up in w.get("upstreamDatasources", []):
            pub_wbs_by_ds.setdefault(up["id"], set()).add(w["id"])
    DF05_WINDOW = 30
    df05_sources = set()
    for d in failed_sources:
        for wid in pub_wbs_by_ds.get(d, ()):
            lvd = wb_last_viewed.get(wid)
            if lvd is not None and lvd <= DF05_WINDOW:
                df05_sources.add(d)
                break
    df05_count = len(df05_sources)

    manifest = {
        "profile": estate["meta"]["profile"],
        "seed": estate["meta"]["seed"],
        "tool_version": estate["meta"]["tool_version"],
        "query_set_version": estate["meta"]["query_set_version"],
        "counts": {
            "projects": len(estate["projects"]),
            "datasources": len(dss),
            "workbooks": len(estate["workbooks"]),
            "fields_total": len(all_fields),
            "calculated_fields": len(calc_fields),
            "max_fields_per_datasource": max_fields,
        },
        "metric_groups": groups,
        "core_metrics": core,
        "dominant_variant_share": round(dom_share, 4),
        "user_context_fields": uc,
        "sec01_expected": uc > 0,
        "nested_calc_max_depth": max_depth,
        "depth_histogram": {str(k): v for k, v in sorted(depth_hist.items())},
        "field_description_coverage": round(coverage, 4),
        "view_concentration": {
            "total_views": total_views,
            "workbooks_total": len(estate["workbooks"]),
            "workbooks_covering_70pct_views": _cover_k(views_by_wb, total_views, 0.7),
            "workbooks_covering_80pct_views": _cover_k(views_by_wb, total_views, 0.8),
            "zero_view_workbooks": zero_view,
        },
        "embedded_share": round(emb_share, 4),
        "provenance": {
            "max_sources_per_upstream_table": max_sources_per_table,
            "max_published_on_published_depth": max_ds_depth,
            "sources_without_upstream": no_upstream,
            "sources_missing_owner": missing_owner,
        },
        "flags_expected": {},
    }

    # R2 extraction ground truth (counts only; no thresholds tuned here). Keyed
    # so the acceptance tests can cross-check the loaded tables against them.
    cs = estate.get("custom_sql", [])
    rj = estate.get("refresh_jobs", [])
    perms = estate.get("permissions", [])
    manifest["custom_sql"] = {
        "count": len(cs),
        "with_group_by": sum(1 for c in cs
                             if _SQL_GROUP_BY_RE.search(c.get("query", ""))),
        "with_user_function": sum(1 for c in cs
                                  if _SQL_USER_FUNC_RE.search(c.get("query", ""))),
    }
    manifest["refresh_jobs"] = {
        "count": len(rj),
        "failed": sum(1 for j in rj if j.get("status") == "Failed"),
        "failed_source_recent_views": df05_count,
    }
    manifest["permissions"] = {
        "count": len(perms),
        "project_level": sum(1 for p in perms if p.get("object_type") == "project"),
        "sampled": sum(1 for p in perms if p.get("sampled")),
    }
    usage_users = set(u.get("user_id") for u in estate["usage_events"]
                      if u.get("user_id"))
    manifest["adoption_depth"] = {
        "events_with_user": sum(1 for u in estate["usage_events"]
                                if u.get("user_id")),
        "distinct_users": len(usage_users),
    }

    # Expected flag firing for the prototype flag set (M5 asserts against this).
    fe = manifest["flags_expected"]
    fe["SEC-01"] = {"fires": uc > 0, "count": uc}
    fe["SEM-01"] = {"fires": any(g["fires_sem01"] for g in groups.values()),
                    "groups": sorted(c for c, g in groups.items() if g["fires_sem01"])}
    fe["SEM-02"] = {"fires": any(g["fires_sem02"] for g in groups.values()),
                    "groups": sorted(c for c, g in groups.items() if g["fires_sem02"])}
    fe["SEM-03"] = {"fires": coverage < 0.40, "coverage": round(coverage, 4)}
    fe["DF-01"] = {"fires": emb_share > 0.60, "embedded_share": round(emb_share, 4)}
    fe["DF-02"] = {"fires": max_sources_per_table > 10, "count": max_sources_per_table}
    fe["DF-03"] = {"fires": max_ds_depth >= 2, "depth": max_ds_depth}
    fe["EST-01"] = {"fires": zero_view > 0, "count": zero_view}
    fe["ADO-02"] = {"fires": True,
                    "workbooks_covering_80pct_views":
                        manifest["view_concentration"]["workbooks_covering_80pct_views"]}
    # R4 flag set. Firing derives from the fixture ground truth above, never from
    # a threshold shaped to the fixture. DF-07 is suppressed (never written) so it
    # is deliberately absent here and asserted via the suppressed log instead.
    rj_total = len(rj)
    rj_failed = manifest["refresh_jobs"]["failed"]
    fe["SEC-02"] = {"fires": sec02 >= 1, "count": sec02}
    fe["SEM-04"] = {"fires": max_fields > 300, "max_field_count": max_fields}
    fe["DF-04"] = {"fires": no_upstream > 0, "count": no_upstream}
    fe["DF-05"] = {"fires": df05_count > 0, "count": df05_count}
    fe["DF-06"] = {"fires": (rj_failed / rj_total) > 0.10 if rj_total else False,
                   "count": rj_failed}
    fe["GOV-01"] = {"fires": missing_owner > 0, "count": missing_owner}
    return manifest


# ---------------------------------------------------------------------------
# Build + assert + write.
# ---------------------------------------------------------------------------

def _strip_private(obj):
    """Return a deep copy with `_`-prefixed keys removed (for a clean estate.json
    we could ship, though we DO keep them in the on-disk fixture so tests and the
    generator can measure -- the fixture CLIENT strips them at serve time)."""
    return obj  # estate.json intentionally retains ground truth; client strips.


def build(profile, seed=None):
    # type: (str, Optional[int]) -> Tuple[dict, dict]
    if profile not in BUILDERS:
        raise ValueError("unknown profile %r" % profile)
    if seed is None:
        seed = SEEDS[profile]
    estate = BUILDERS[profile](seed)
    _enrich_r2(estate, seed)   # additive: refresh_jobs/custom_sql/permissions + usage identity
    manifest = measure(estate)
    _assert_profile(profile, estate, manifest)
    return estate, manifest


def _assert_profile(profile, estate, m):
    # type: (str, dict, dict) -> None
    if profile == "median":
        c = m["counts"]
        assert c["workbooks"] == 1000, c["workbooks"]
        assert c["datasources"] == 200, c["datasources"]
        rev = m["metric_groups"]["revenue"]
        assert rev["variants"] == 47, rev
        assert rev["variants_covering_80pct_views"] == 3, rev
        assert rev["dominant"] is True, rev
        ac = m["metric_groups"]["active_customer"]
        assert ac["variants"] == 14, ac
        assert ac["dominant"] is False, ac
        assert ac["disagreeing_variants"] == 9, ac
        assert m["user_context_fields"] >= 20, m["user_context_fields"]
        assert m["nested_calc_max_depth"] in (3, 4), m["nested_calc_max_depth"]
        assert m["nested_calc_max_depth"] == 4, m["nested_calc_max_depth"]
        assert m["depth_histogram"].get("3", 0) >= 1, m["depth_histogram"]
        conc = m["view_concentration"]
        assert conc["workbooks_covering_70pct_views"] < 300, conc
        assert conc["zero_view_workbooks"] > 0, conc
        assert m["field_description_coverage"] >= 0.40, m["field_description_coverage"]
        assert abs(m["dominant_variant_share"] - 0.2) < 1e-9, m["dominant_variant_share"]
        assert m["embedded_share"] > 0.60, m["embedded_share"]
        assert m["provenance"]["max_sources_per_upstream_table"] > 10, m["provenance"]
        assert m["provenance"]["max_published_on_published_depth"] >= 2, m["provenance"]
        # four differently-named revenue variants present
        names = set()
        for ds in estate["datasources"]:
            for f in ds["fields"]:
                if f.get("_concept") == "revenue":
                    names.add(f["name"])
        for want in ["Revenue", "Total Revenue", "Net Rev", "Rev USD"]:
            assert want in names, ("missing revenue variant name %r" % want)
    elif profile == "small":
        assert m["counts"]["workbooks"] == 100, m["counts"]
        assert not m["flags_expected"]["SEC-01"]["fires"]
        assert not m["flags_expected"]["SEM-02"]["fires"]
    elif profile == "hostile":
        # hostile is validated in M3; here just ensure it built and has calcs
        assert m["counts"]["calculated_fields"] > 0


def write_fixture(profile, out_dir, seed=None):
    # type: (str, str, Optional[int]) -> Tuple[str, str]
    estate, manifest = build(profile, seed)
    d = os.path.join(out_dir, profile)
    if not os.path.isdir(d):
        os.makedirs(d)
    estate_path = os.path.join(d, "estate.json")
    manifest_path = os.path.join(d, "manifest.json")
    with open(estate_path, "w") as fh:
        json.dump(estate, fh, indent=1, sort_keys=False)
        fh.write("\n")
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return estate_path, manifest_path
