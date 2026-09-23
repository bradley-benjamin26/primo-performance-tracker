"""Polls the UMD Primo search API with show_performance=true and logs timing data to CSV.

Primo's discovery/search page is an Angular SPA; the show_performance panel it renders is
just a display of the JSON already returned by the underlying primaws/rest/pub/pnxs search
API. Hitting that API directly avoids needing a browser.
"""
import csv
import datetime
import os
import sys
from pathlib import Path

import requests

API_URL = "https://usmai-umcp.primo.exlibrisgroup.com/primaws/rest/pub/pnxs"

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

# Search terms to rotate through on every run. Edit this list to change what gets sampled.
SEARCH_TERMS = ["test", "history", "science", "a"]

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

FIELDNAMES = ["timestamp_utc", "search_term"] + INFO_FIELDS + TIMELOG_FIELDS

DATA_FILE = Path(__file__).parent / "data" / "performance_log.csv"


def fetch_performance(search_term: str) -> dict:
    """Query the Primo search API for one term and return its parsed JSON body."""
    params = dict(BASE_PARAMS)
    params["q"] = f"any,contains,{search_term}"
    response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def build_row(search_term: str, payload: dict, now: datetime.datetime = None) -> dict:
    """Flatten one API response's timelog/info data into a single CSV row."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    timelog = payload.get("timelog", {})
    info = payload.get("info", {})

    row = {"timestamp_utc": now.isoformat(), "search_term": search_term}
    for field in INFO_FIELDS:
        row[field] = info.get(field, "")
    for field in TIMELOG_FIELDS:
        row[field] = timelog.get(field, "")
    return row


def append_rows(rows: list, path: Path = DATA_FILE) -> None:
    """Append rows to the CSV log, writing the header first if the file is new."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run(search_terms: list = None) -> list:
    """Fetch performance data for each search term and append it to the CSV log."""
    search_terms = search_terms or SEARCH_TERMS
    rows = []
    for term in search_terms:
        try:
            payload = fetch_performance(term)
        except requests.RequestException as exc:
            print(f"Request failed for term {term!r}: {exc}", file=sys.stderr)
            continue
        rows.append(build_row(term, payload))
    append_rows(rows)
    return rows


if __name__ == "__main__":
    result_rows = run()
    print(f"Logged {len(result_rows)} row(s) to {DATA_FILE}")
