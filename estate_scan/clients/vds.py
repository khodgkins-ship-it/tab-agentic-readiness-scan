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

from typing import List, Optional

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
        # type: (str, str, Optional[str], Optional[str], Optional[str]) -> dict
        """Build a read-only aggregate query body: one measure, optionally scoped
        to a fixed period by a categorical (SET) filter. Emits only read keys, so
        it passes `assert_vds_body_read_only` by construction.

        A falsy `function` (None or "") omits the `function` key so the field is
        returned with its *native* aggregation. That is required for a calculated
        field whose formula already aggregates (COUNTD, SUM(..)/SUM(..), a FIXED
        LOD, ...): VDS rejects an outer SUM on such a field (errorCode 400800), and
        even when a function is accepted VDS keys the output column ``FN(caption)``
        rather than the bare caption -- so `VdsResult.value(caption)` only resolves
        the native (no-function) form. See `derive/disagreement.vds_function`."""
        spec = {"fieldCaption": field_caption}
        if function:
            spec["function"] = function
        query = {"fields": [spec]}
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

    # -- grouped reads (R2 usage extraction) ---------------------------------
    # The single-measure builder above is enough for material disagreement (one
    # aggregate per variant). Usage extraction needs a *grouped* aggregate: one
    # row per workbook carrying its view count and last-viewed date. That is
    # still a read -- dimensions + aggregated measures + filters -- so it passes
    # `assert_vds_body_read_only` by the same construction (only fields/filters
    # under query; the guard never inspects a field's function or a filter's
    # predicate, so multiple measures and a date-range filter are admitted).

    @staticmethod
    def build_grouped_query(datasource_luid, dimensions, measures, filters=None):
        # type: (str, List[str], List[tuple], Optional[List[dict]]) -> dict
        """Build a read-only grouped aggregate body.

        `dimensions` are field captions returned raw (the GROUP BY). `measures`
        are ``(caption, function, alias)`` triples; the alias names the output
        column so two aggregates of the *same* field (e.g. COUNT and MAX of the
        event timestamp) do not collide on one key. `filters` are prebuilt
        read-only filter objects (see `match_filter`/`since_date_filter`)."""
        fields = [{"fieldCaption": c} for c in dimensions]
        for caption, function, alias in measures:
            spec = {"fieldCaption": caption, "function": function}
            if alias:
                spec["fieldAlias"] = alias
            fields.append(spec)
        query = {"fields": fields}
        if filters:
            query["filters"] = list(filters)
        return {"datasource": {"datasourceLuid": datasource_luid}, "query": query}

    @staticmethod
    def match_filter(field_caption, values):
        # type: (str, List[str]) -> dict
        """A categorical (SET) filter: keep rows whose field is in `values`."""
        return {"field": {"fieldCaption": field_caption},
                "filterType": "SET", "values": list(values)}

    @staticmethod
    def since_date_filter(field_caption, min_date):
        # type: (str, str) -> dict
        """A one-sided date-range filter: keep rows at or after `min_date`
        (ISO date). Bounds the window so the read never pulls the full history."""
        return {"field": {"fieldCaption": field_caption},
                "filterType": "QUANTITATIVE_DATE",
                "quantitativeFilterType": "MIN", "minDate": min_date}

    def execute_grouped(self, datasource_luid, dimensions, measures, filters=None):
        # type: (str, List[str], List[tuple], Optional[List[dict]]) -> VdsResult
        """Issue one grouped read and return the raw `VdsResult`; the caller reads
        `result.data` (a list of rows keyed by caption/alias)."""
        body = self.build_grouped_query(datasource_luid, dimensions, measures,
                                        filters)
        return self._client.vds_query(body)
