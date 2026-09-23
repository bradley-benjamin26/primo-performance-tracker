"""Polls the UMD Primo search API with show_performance=true and logs timing data to CSV.

Primo's discovery/search page is an Angular SPA; the show_performance panel it renders is
just a display of the JSON already returned by the underlying primaws/rest/pub/pnxs search
API. Hitting that API directly avoids needing a browser.
"""
import csv
import datetime
import sys
import time
from pathlib import Path

import requests

API_URL = "https://usmai-umcp.primo.exlibrisgroup.com/primaws/rest/pub/pnxs"

# Identifies this traffic as an automated monitor in server logs, distinct from real patron
# searches, so it can be excluded from usage/"popular searches" reporting if needed.
REQUEST_HEADERS = {
    "User-Agent": (
        "primo-performance-tracker/1.0 "
        "(+https://github.com/bradley-benjamin26/primo-performance-tracker; "
        "automated uptime/latency monitor, not a patron search; "
        "contact: bbradle1@umd.edu)"
    )
}

# Static params matching the UMD Primo "Everything" search scope used in the discovery UI.
BASE_PARAMS = {
    "blendFacetsSeparately": "false",
    "getMore": "0",
    "inst": "01USMAI_UMCP",
    "lang": "en",
    "limit": "1",
    "offset": "0",
    "pcAvailability": "false",
    "qExclude": "",
    "qInclude": "",
    "rapido": "false",
    "refEntryActive": "false",
    "rtaLinks": "true",
    "scope": "DN_and_CI",
    "searchInFulltextUserSelection": "false",
    "skipDelivery": "Y",
    "sort": "rank",
    "tab": "Everything",
    "vid": "01USMAI_UMCP:UMCP",
    "show_performance": "true",
}

# How many top results to capture per search, for eyeballing whether odd results show up.
RESULTS_PER_TERM = 5

# Search terms to rotate through on every run. Edit this list to change what gets sampled.
SEARCH_TERMS = ["test", "history", "science", "maryland history", "linear algebra", "Migration and Labor 1900", "cats AND dogs", "saltwater encroachment AND climate change"]

REQUEST_TIMEOUT = 30

# Known timelog/info fields, used as a stable CSV column order. Any new fields Primo starts
# returning are still captured (see EXTRA_FIELDS handling in append_row) but won't have a
# dedicated column until added here.
TIMELOG_FIELDS = [
    "COMBINED_SEARCH_TIME",
    "PRIMA_LOCAL_SEARCH_TOTAL",
    "PRIMA_LOCAL_INFO_FACETS_BUILD_DOCS_HIGHLIGHTS",
    "CALL_SOLR_GET_IDS_LIST",
    "BUILD_RESULTS_RETRIVE_FROM_DB",
    "RETRIVE_FROM_DB_RECORDS",
    "RETRIVE_FROM_DB_COURSE_INFO",
    "RETRIVE_FROM_DB_RELATIONS",
    "PC_SEARCH_TIME_TOTAL",
    "PC_SEARCH_CALL_TIME",
    "PC_BUILD_JSON_AND_HIGLIGHTS",
    "BUILD_BLEND_AND_CACHE_RESULTS",
    "BUILD_COMBINED_RESULTS_MAP",
    "PROCESS_COMBINED_RESULTS",
    "FEATURED_SEARCH_TIME",
]

INFO_FIELDS = ["totalResultsLocal", "totalResultsPC", "total", "first", "last"]

# Fields describing the HTTP request itself, independent of what Primo's own timelog reports -
# catches network/CDN slowness and outright failures (timeouts, non-200s) that show up nowhere
# in the server-reported timings.
REQUEST_FIELDS = ["client_latency_ms", "http_status", "request_error"]

# A run-over-run change in `total` results for the same term at or above this percentage is
# flagged as a possible anomaly (e.g. an index/connector outage silently dropping results).
ANOMALY_PCT_THRESHOLD = 50

ANOMALY_FIELDS = ["zero_results", "total_change_pct", "result_count_anomaly"]

FIELDNAMES = (
    ["timestamp_utc", "search_term"] + INFO_FIELDS + TIMELOG_FIELDS + REQUEST_FIELDS + ANOMALY_FIELDS
)

RESULT_FIELDNAMES = ["timestamp_utc", "search_term", "rank", "title"]

DATA_FILE = Path(__file__).parent / "data" / "performance_log.csv"
RESULTS_FILE = Path(__file__).parent / "data" / "results_log.csv"


def fetch_performance(search_term: str) -> requests.Response:
    """Query the Primo search API for one term and return the raw response.

    Callers are responsible for checking response.ok / status_code themselves, since a non-200
    response is itself a signal worth logging rather than an exception to swallow.
    """
    params = dict(BASE_PARAMS)
    params["q"] = f"any,contains,{search_term}"
    params["limit"] = str(RESULTS_PER_TERM)
    return requests.get(API_URL, params=params, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)


def load_previous_totals(path: Path = DATA_FILE) -> dict:
    """Read the most recently logged `total` result count per search term from the CSV log."""
    if not path.exists():
        return {}
    totals = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                totals[row["search_term"]] = int(row["total"])
            except (KeyError, ValueError):
                continue
    return totals


def build_row(
    search_term: str,
    payload: dict,
    now: datetime.datetime = None,
    client_latency_ms: float = "",
    http_status="",
    request_error: str = "",
    previous_total: int = None,
) -> dict:
    """Flatten one API response's timelog/info data, request diagnostics, and anomaly
    flags (vs. the previous logged run for this term) into a single CSV row."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    timelog = payload.get("timelog", {})
    info = payload.get("info", {})

    row = {"timestamp_utc": now.isoformat(), "search_term": search_term}
    for field in INFO_FIELDS:
        row[field] = info.get(field, "")
    for field in TIMELOG_FIELDS:
        row[field] = timelog.get(field, "")

    row["client_latency_ms"] = client_latency_ms
    row["http_status"] = http_status
    row["request_error"] = request_error

    total = info.get("total")
    zero_results = total == 0
    row["zero_results"] = zero_results

    total_change_pct = ""
    count_anomaly = False
    if total is not None and previous_total:
        total_change_pct = round(abs(total - previous_total) / previous_total * 100, 1)
        count_anomaly = total_change_pct >= ANOMALY_PCT_THRESHOLD
    row["total_change_pct"] = total_change_pct
    row["result_count_anomaly"] = zero_results or count_anomaly

    return row


def build_result_rows(search_term: str, payload: dict, now: datetime.datetime = None) -> list:
    """Flatten the top N returned docs into one CSV row per result, for spotting odd results."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    rows = []
    for rank, doc in enumerate(payload.get("docs", []), start=1):
        display = doc.get("pnx", {}).get("display", {})
        rows.append(
            {
                "timestamp_utc": now.isoformat(),
                "search_term": search_term,
                "rank": rank,
                "title": "; ".join(display.get("title", [])),
            }
        )
    return rows


def append_rows(rows: list, path: Path, fieldnames: list) -> None:
    """Append rows to a CSV log, writing the header first if the file is new."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def next_search_term() -> str:
    """Pick the next term to sample, rotating through SEARCH_TERMS one at a time.

    The rotation position is derived from how many rows are already logged, so state doesn't
    need to be tracked separately - each scheduled run searches exactly one term instead of
    battering the search API with the whole list every 30 minutes.
    """
    logged_count = 0
    if DATA_FILE.exists():
        with open(DATA_FILE, newline="") as f:
            logged_count = sum(1 for _ in csv.DictReader(f))
    return SEARCH_TERMS[logged_count % len(SEARCH_TERMS)]


def run(search_terms: list = None) -> tuple:
    """Fetch performance and top-result data for each search term and log both to CSV.

    With no `search_terms` given, only one term is searched per call (see next_search_term) to
    keep this monitor's footprint on the production search system minimal.
    """
    search_terms = search_terms if search_terms is not None else [next_search_term()]
    previous_totals = load_previous_totals()
    perf_rows = []
    result_rows = []
    for term in search_terms:
        payload = {}
        http_status = ""
        request_error = ""
        start = time.monotonic()
        try:
            response = fetch_performance(term)
            http_status = response.status_code
            if response.ok:
                payload = response.json()
            else:
                request_error = f"HTTP {http_status}"
        except requests.RequestException as exc:
            request_error = str(exc)
            print(f"Request failed for term {term!r}: {exc}", file=sys.stderr)
        client_latency_ms = round((time.monotonic() - start) * 1000, 1)

        perf_rows.append(
            build_row(
                term,
                payload,
                client_latency_ms=client_latency_ms,
                http_status=http_status,
                request_error=request_error,
                previous_total=previous_totals.get(term),
            )
        )
        if payload:
            result_rows.extend(build_result_rows(term, payload))
    append_rows(perf_rows, DATA_FILE, FIELDNAMES)
    append_rows(result_rows, RESULTS_FILE, RESULT_FIELDNAMES)
    return perf_rows, result_rows


if __name__ == "__main__":
    performance_rows, top_result_rows = run()
    print(f"Logged {len(performance_rows)} performance row(s) to {DATA_FILE}")
    print(f"Logged {len(top_result_rows)} result row(s) to {RESULTS_FILE}")
