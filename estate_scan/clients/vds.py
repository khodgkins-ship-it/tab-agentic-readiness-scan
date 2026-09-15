"""The VizQL Data Service executor: read-only aggregate reads (R3).

VDS is the *consequence* layer for material disagreement. SEM-02 in the scan is
a structural proxy -- distinct resolved definitions among the used variants of a
metric. This executor takes two such variants and asks the site what each one
actually returns for one agreed period, so a report can show the dollar gap, not
just that the formulas differ (the single most persuasive report element,
04 §4.2).

It is read-only by construction, not by convention:

  * the only body it builds is `datasource` + `query{fields[, filters]}` -- an
    aggregate read; no publish/update/create form exists anywhere in the module;
  * that body is re-validated with `assert_vds_body_read_only` inside
    `LiveClient.vds_query` before issue, and the transport guard (`ReadOnlyGuard`,
    Gate C) refuses any VDS POST that is not to query-datasource or that carries a
    non-read key;
  * queries are parameterized (a resolved variant caption + fixed period), never
    freeform SQL, so there is no raw-query surface.

The executor holds no policy about *which* variants to run or what counts as
material -- that lives in `derive/disagreement.py`. It only builds bodies, issues
them through the guarded session, and reports whether the service is available.
"""

from typing import Optional

from estate_scan.clients.base import VdsResult


class VdsExecutor(object):
    def __init__(self, client):
        # type: (object) -> None
        # Any object exposing `capabilities` + `vds_query(body) -> VdsResult`
        # (production: a connected `LiveClient`). Kept duck-typed so tests can
        # drive the real client over a mock transport, or a stand-in.
        self._client = client

    @property
    def available(self):
        # type: () -> bool
        caps = getattr(self._client, "capabilities", None) or {}
        return bool(caps.get("vizql_data_service"))

    @staticmethod
    def build_query_body(datasource_luid, field_caption, function="SUM",
                         period_field=None, period_value=None):
        # type: (str, str, str, Optional[str], Optional[str]) -> dict
        """Build a read-only aggregate query body: one measure, optionally scoped
        to a fixed period by a categorical (SET) filter. Emits only read keys, so
        it passes `assert_vds_body_read_only` by construction."""
        query = {"fields": [{"fieldCaption": field_caption, "function": function}]}
        if period_field and period_value is not None:
            query["filters"] = [{
                "field": {"fieldCaption": period_field},
                "filterType": "SET",
                "values": [period_value],
            }]
        return {"datasource": {"datasourceLuid": datasource_luid}, "query": query}

    def execute_measure(self, datasource_luid, field_caption, function="SUM",
                        period_field=None, period_value=None):
        # type: (str, str, str, Optional[str], Optional[str]) -> VdsResult
        """Aggregate one measure and return the raw `VdsResult`. The caller reads
        the figure via `result.value(field_caption)`."""
        body = self.build_query_body(datasource_luid, field_caption, function,
                                     period_field, period_value)
        return self._client.vds_query(body)
