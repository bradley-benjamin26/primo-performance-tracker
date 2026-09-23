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


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data


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

    for field in tracker.INFO_FIELDS + tracker.TIMELOG_FIELDS + tracker.REQUEST_FIELDS:
        assert row[field] == ""
    assert row["zero_results"] is False
    assert row["result_count_anomaly"] is False


def test_build_row_captures_request_diagnostics():
    row = tracker.build_row(
        "x",
        {},
        client_latency_ms=842.3,
        http_status=503,
        request_error="HTTP 503",
    )

    assert row["client_latency_ms"] == 842.3
    assert row["http_status"] == 503
    assert row["request_error"] == "HTTP 503"


def test_build_row_flags_zero_results():
    row = tracker.build_row("x", {"info": {"total": 0}, "timelog": {}})

    assert row["zero_results"] is True
    assert row["result_count_anomaly"] is True


def test_build_row_flags_large_result_count_swing():
    row = tracker.build_row("x", {"info": {"total": 100}, "timelog": {}}, previous_total=1000)

    assert row["total_change_pct"] == 90.0
    assert row["result_count_anomaly"] is True


def test_build_row_does_not_flag_small_result_count_swing():
    row = tracker.build_row("x", {"info": {"total": 950}, "timelog": {}}, previous_total=1000)

    assert row["total_change_pct"] == 5.0
    assert row["result_count_anomaly"] is False


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


def test_load_previous_totals_reads_last_total_per_term(tmp_path):
    path = tmp_path / "log.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["search_term", "total"])
        writer.writeheader()
        writer.writerow({"search_term": "history", "total": "100"})
        writer.writerow({"search_term": "history", "total": "150"})
        writer.writerow({"search_term": "science", "total": "200"})

    totals = tracker.load_previous_totals(path)

    assert totals == {"history": 150, "science": 200}


def test_load_previous_totals_missing_file_returns_empty_dict(tmp_path):
    assert tracker.load_previous_totals(tmp_path / "missing.csv") == {}


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
        return FakeResponse(json_data=SAMPLE_PAYLOAD)

    def fake_append(rows, path, fieldnames):
        appended[path] = rows

    monkeypatch.setattr(tracker, "fetch_performance", fake_fetch)
    monkeypatch.setattr(tracker, "append_rows", fake_append)
    monkeypatch.setattr(tracker, "load_previous_totals", lambda: {})

    perf_rows, result_rows = tracker.run(search_terms=["alpha", "beta"])

    assert fetch_calls == ["alpha", "beta"]
    assert [r["search_term"] for r in perf_rows] == ["alpha", "beta"]
    assert all(r["http_status"] == 200 and r["request_error"] == "" for r in perf_rows)
    assert all(isinstance(r["client_latency_ms"], float) for r in perf_rows)
    assert [r["search_term"] for r in result_rows] == ["alpha", "alpha", "beta", "beta"]
    assert appended[tracker.DATA_FILE] == perf_rows
    assert appended[tracker.RESULTS_FILE] == result_rows


def test_run_logs_but_does_not_crash_on_request_exception(monkeypatch):
    def fake_fetch(term):
        if term == "bad":
            raise tracker.requests.RequestException("boom")
        return FakeResponse(json_data=SAMPLE_PAYLOAD)

    monkeypatch.setattr(tracker, "fetch_performance", fake_fetch)
    monkeypatch.setattr(tracker, "append_rows", lambda rows, path, fieldnames: None)
    monkeypatch.setattr(tracker, "load_previous_totals", lambda: {})

    perf_rows, result_rows = tracker.run(search_terms=["good", "bad"])

    assert [r["search_term"] for r in perf_rows] == ["good", "bad"]
    bad_row = perf_rows[1]
    assert bad_row["request_error"] == "boom"
    assert bad_row["http_status"] == ""
    # A failed fetch has no docs, so no result rows are produced for it.
    assert [r["search_term"] for r in result_rows] == ["good", "good"]


def test_run_logs_non_200_response_without_crashing(monkeypatch):
    def fake_fetch(term):
        return FakeResponse(status_code=503, json_data={})

    monkeypatch.setattr(tracker, "fetch_performance", fake_fetch)
    monkeypatch.setattr(tracker, "append_rows", lambda rows, path, fieldnames: None)
    monkeypatch.setattr(tracker, "load_previous_totals", lambda: {})

    perf_rows, result_rows = tracker.run(search_terms=["down"])

    assert perf_rows[0]["http_status"] == 503
    assert perf_rows[0]["request_error"] == "HTTP 503"
    assert result_rows == []
