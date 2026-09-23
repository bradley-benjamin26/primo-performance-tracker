import csv
import datetime

import pytest

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


def test_append_rows_writes_header_once(tmp_path):
    path = tmp_path / "log.csv"
    row = tracker.build_row("test", SAMPLE_PAYLOAD)

    tracker.append_rows([row], path=path)
    tracker.append_rows([row], path=path)

    with open(path, newline="") as f:
        lines = list(csv.reader(f))

    assert lines[0] == tracker.FIELDNAMES
    assert len(lines) == 3  # header + 2 data rows


def test_run_fetches_each_term_and_appends(monkeypatch):
    fetch_calls = []
    appended = []

    def fake_fetch(term):
        fetch_calls.append(term)
        return SAMPLE_PAYLOAD

    monkeypatch.setattr(tracker, "fetch_performance", fake_fetch)
    monkeypatch.setattr(tracker, "append_rows", lambda rows: appended.extend(rows))

    rows = tracker.run(search_terms=["alpha", "beta"])

    assert fetch_calls == ["alpha", "beta"]
    assert [r["search_term"] for r in rows] == ["alpha", "beta"]
    assert appended == rows


def test_run_skips_term_on_request_failure(monkeypatch):
    def fake_fetch(term):
        if term == "bad":
            raise tracker.requests.RequestException("boom")
        return SAMPLE_PAYLOAD

    monkeypatch.setattr(tracker, "fetch_performance", fake_fetch)
    monkeypatch.setattr(tracker, "append_rows", lambda rows: None)

    rows = tracker.run(search_terms=["good", "bad"])

    assert [r["search_term"] for r in rows] == ["good"]
