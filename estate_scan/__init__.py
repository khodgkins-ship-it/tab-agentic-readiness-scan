"""Estate Scan — a Tableau estate readiness assessment pipeline.

Five stages, each independently runnable against the previous stage's output:

    extract  ->  store  ->  derive  ->  flag  ->  report

The prototype runs entirely offline against recorded fixtures. The client
interface (estate_scan.clients.base) is what keeps the pipeline honest: the
fixture client and the live clients satisfy the same contract, so no stage
knows which it is talking to.
"""

TOOL_VERSION = "0.1.0"
QUERY_SET_VERSION = "v1"
APP_TEMPLATE_VERSION = "1"  # web app template, versioned independently of the tool
