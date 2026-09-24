# primo-performance-tracker

Polls the UMD Primo discovery search (`show_performance=true`) every 15 minutes via GitHub
Actions and logs the server-side timing breakdown to [data/performance_log.csv](data/performance_log.csv),
plus the titles of the top results to [data/results_log.csv](data/results_log.csv) so odd results
are easy to spot over time.

## How it works

The Primo discovery search page is an Angular single-page app, so the `show_performance=true`
panel you see in the browser is just a rendering of JSON that's already returned by the
underlying search API (`primaws/rest/pub/pnxs`). [tracker.py](tracker.py) calls that API
directly, searching **one term per run** - rotating through `SEARCH_TERMS` (based on how many
rows are already logged, so no separate state needs to be tracked) rather than firing the whole
list every run - and appends:

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

- searches only one term per run (see above) instead of a batch of terms, to keep its
  load on the system minimal
- sends an identifying `User-Agent` (see `REQUEST_HEADERS` in [tracker.py](tracker.py)) so
  library staff reviewing search logs or "popular searches" usage reports can recognize and
  filter out this traffic

Note that hitting the JSON API directly (rather than loading the full page) means this traffic
never triggers browser-side analytics (Google Analytics, etc.), since those only fire from a
real browser executing the page's JS. It can still be recorded in Primo/Alma's own backend
search logs like any other API request, which is what the `User-Agent` is for.

## Scheduling

GitHub Actions' own `schedule` trigger is unreliable at sub-hourly frequency - in practice a
`*/15 * * * *` cron on this repo ran only a few times a day, hours apart, instead of every 15
minutes. GitHub Actions schedules are documented as best-effort and get deprioritized for
low-activity/free-tier repos, so this isn't specific to this project's workflow config.

The actual 15-minute cadence comes from an **external scheduler** (e.g.
[cron-job.org](https://cron-job.org)) that calls the GitHub REST API every 15 minutes to fire a
`workflow_dispatch` event directly:

```
POST https://api.github.com/repos/bradley-benjamin26/primo-performance-tracker/actions/workflows/track.yml/dispatches
Authorization: Bearer <fine-grained PAT, scoped to this repo, Actions: read/write only>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json

{"ref": "main"}
```

`workflow_dispatch`-triggered runs aren't subject to the same scheduling throttle as `schedule`
events, so this is far more reliable for a tight interval. The `schedule: "*/15 * * * *"` cron
in [.github/workflows/track.yml](.github/workflows/track.yml) is left in place only as a
low-cost fallback in case the external scheduler goes down; it can also always be triggered
manually from the Actions tab.

## Tests

```bash
pip install pytest
pytest
```
