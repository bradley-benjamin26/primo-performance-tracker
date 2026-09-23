import csv
import datetime

import tracker


SAMPLE_PAYLOAD = {
    "info": {
        "totalResultsLocal": 95065,
        "totalResultsPC": 9303549,
        "total": 9398614,
        "first": 1,
        "last": 1,
    },
    "timelog": {
        "COMBINED_SEARCH_TIME": 353,
        "PRIMA_LOCAL_SEARCH_TOTAL": "314",
        "PC_SEARCH_TIME_TOTAL": "163",
        "PC_SEARCH_CALL_TIME": "78",
    },
    "docs": [
        {"pnx": {"display": {"title": ["Climate change and infrastructure"]}}},
        {"pnx": {"display": {"title": ["Some article"]}}},
    ],
}


def test_build_row_flattens_info_and_timelog():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    row = tracker.build_row("TEst", SAMPLE_PAYLOAD, now=now)

    assert row["timestamp_utc"] == now.isoformat()
    assert row["search_term"] == "TEst"
    assert row["totalResultsLocal"] == 95065
    assert row["COMBINED_SEARCH_TIME"] == 353
    assert row["PC_SEARCH_CALL_TIME"] == "78"


def test_build_row_fills_missing_fields_with_empty_string():
    row = tracker.build_row("x", {"info": {}, "timelog": {}})

    for field in tracker.INFO_FIELDS + tracker.TIMELOG_FIELDS:
        assert row[field] == ""


def test_build_result_rows_flattens_top_docs():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    rows = tracker.build_result_rows("climate", SAMPLE_PAYLOAD, now=now)

    assert len(rows) == 2
    assert rows[0]["rank"] == 1
    assert rows[0]["search_term"] == "climate"
    assert rows[0]["title"] == "Climate change and infrastructure"
    assert rows[1]["rank"] == 2
    assert rows[1]["title"] == "Some article"


def test_build_result_rows_handles_no_docs():
    assert tracker.build_result_rows("empty", {"docs": []}) == []


def test_append_rows_writes_header_once(tmp_path):
    path = tmp_path / "log.csv"
    row = tracker.build_row("test", SAMPLE_PAYLOAD)

    tracker.append_rows([row], path, tracker.FIELDNAMES)
    tracker.append_rows([row], path, tracker.FIELDNAMES)

    with open(path, newline="") as f:
        lines = list(csv.reader(f))

    assert lines[0] == tracker.FIELDNAMES
    assert len(lines) == 3  # header + 2 data rows


def test_run_fetches_each_term_and_logs_performance_and_results(monkeypatch):
    fetch_calls = []
    appended = {}

    def fake_fetch(term):
        fetch_calls.append(term)
        return SAMPLE_PAYLOAD

    def fake_append(rows, path, fieldnames):
        appended[path] = rows

    monkeypatch.setattr(tracker, "fetch_performance", fake_fetch)
    monkeypatch.setattr(tracker, "append_rows", fake_append)

    perf_rows, result_rows = tracker.run(search_terms=["alpha", "beta"])

    assert fetch_calls == ["alpha", "beta"]
    assert [r["search_term"] for r in perf_rows] == ["alpha", "beta"]
    assert [r["search_term"] for r in result_rows] == ["alpha", "alpha", "beta", "beta"]
    assert appended[tracker.DATA_FILE] == perf_rows
    assert appended[tracker.RESULTS_FILE] == result_rows


def test_run_skips_term_on_request_failure(monkeypatch):
    def fake_fetch(term):
        if term == "bad":
            raise tracker.requests.RequestException("boom")
        return SAMPLE_PAYLOAD

    monkeypatch.setattr(tracker, "fetch_performance", fake_fetch)
    monkeypatch.setattr(tracker, "append_rows", lambda rows, path, fieldnames: None)

    perf_rows, result_rows = tracker.run(search_terms=["good", "bad"])

    assert [r["search_term"] for r in perf_rows] == ["good"]
    assert [r["search_term"] for r in result_rows] == ["good", "good"]
