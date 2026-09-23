# primo-performance-tracker

Polls the UMD Primo discovery search (`show_performance=true`) every 30 minutes via GitHub
Actions and logs the server-side timing breakdown to [data/performance_log.csv](data/performance_log.csv),
plus the titles of the top results to [data/results_log.csv](data/results_log.csv) so odd results
are easy to spot over time.

## How it works

The Primo discovery search page is an Angular single-page app, so the `show_performance=true`
panel you see in the browser is just a rendering of JSON that's already returned by the
underlying search API (`primaws/rest/pub/pnxs`). [tracker.py](tracker.py) calls that API
directly for each term in `SEARCH_TERMS` and, per run, appends:

- one row per term to `performance_log.csv`, containing `totalResultsLocal`, `totalResultsPC`,
  `total`, and the `timelog` sub-timings Primo reports (`COMBINED_SEARCH_TIME`,
  `PRIMA_LOCAL_SEARCH_TOTAL`, `PC_SEARCH_TIME_TOTAL`, Solr calls, DB retrieval, JSON building, etc.)
- one row per top result (`RESULTS_PER_TERM`, default 5) to `results_log.csv`, containing just
  the term, rank, and title

## Local usage

```bash
pip install -r requirements.txt
python tracker.py
```

## Customizing search terms

Edit the `SEARCH_TERMS` list in [tracker.py](tracker.py) to change what gets sampled each run.

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
