# primo-performance-tracker

Polls the UMD Primo discovery search (`show_performance=true`) every 30 minutes via GitHub
Actions and logs the server-side timing breakdown to [data/performance_log.csv](data/performance_log.csv),
plus the titles of the top results to [data/results_log.csv](data/results_log.csv) so odd results
are easy to spot over time.

## How it works

The Primo discovery search page is an Angular single-page app, so the `show_performance=true`
panel you see in the browser is just a rendering of JSON that's already returned by the
underlying search API (`primaws/rest/pub/pnxs`). [tracker.py](tracker.py) calls that API
directly, searching **one term per run** - rotating through `SEARCH_TERMS` (based on how many
rows are already logged, so no separate state needs to be tracked) rather than firing the whole
list every 30 minutes - and appends:

- one row per term to `performance_log.csv`, containing:
  - `totalResultsLocal`, `totalResultsPC`, `total`, and the `timelog` sub-timings Primo reports
    (`COMBINED_SEARCH_TIME`, `PRIMA_LOCAL_SEARCH_TOTAL`, `PC_SEARCH_TIME_TOTAL`, Solr calls, DB
    retrieval, JSON building, etc.) — all server-reported
  - `client_latency_ms`, `http_status`, `request_error` — the *client-side* wall-clock time and
    outcome of the request itself, which catches network/CDN slowness, timeouts, and non-200
    responses that never show up in Primo's own self-reported timings
  - `zero_results`, `total_change_pct`, `result_count_anomaly` — flags a term whose `total`
    result count is 0, or has swung by `ANOMALY_PCT_THRESHOLD`% (default 50%) or more since the
    last time that term was logged, as a possible sign of an index or connector outage
- one row per top result (`RESULTS_PER_TERM`, default 5) to `results_log.csv`, containing just
  the term, rank, and title

## Local usage

```bash
pip install -r requirements.txt
python tracker.py
```

## Customizing search terms

Edit the `SEARCH_TERMS` list in [tracker.py](tracker.py) to change what gets sampled. Each run
searches exactly one term from that list, moving to the next on the following run.

## Being a good citizen of the production search system

This hits the same production search API that patrons use, so it:

- searches only one term per 30-minute run (see above) instead of a batch of terms, to keep its
  load on the system minimal
- sends an identifying `User-Agent` (see `REQUEST_HEADERS` in [tracker.py](tracker.py)) so
  library staff reviewing search logs or "popular searches" usage reports can recognize and
  filter out this traffic

Note that hitting the JSON API directly (rather than loading the full page) means this traffic
never triggers browser-side analytics (Google Analytics, etc.), since those only fire from a
real browser executing the page's JS. It can still be recorded in Primo/Alma's own backend
search logs like any other API request, which is what the `User-Agent` is for.

## Scheduling

[.github/workflows/track.yml](.github/workflows/track.yml) runs the script every 30 minutes via
`cron: "*/30 * * * *"` and commits the updated CSV back to the repo. It can also be triggered
manually from the Actions tab (`workflow_dispatch`).

Note: GitHub Actions schedules are best-effort and can be delayed during high load, so runs
won't always land exactly on the 30-minute mark.

## Tests

```bash
pip install pytest
pytest
```
