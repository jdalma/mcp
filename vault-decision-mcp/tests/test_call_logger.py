# tests/test_call_logger.py
import importlib
import json


def test_rotation(tmp_path, monkeypatch):
    import call_logger

    monkeypatch.setattr(call_logger, "LOG_DIR", tmp_path)

    monkeypatch.setattr(call_logger, "_now", lambda: "2026-01-15T12:00:00")
    call_logger.log_call("query", {"q": "a"}, {"hits": 1}, 10.0)

    monkeypatch.setattr(call_logger, "_now", lambda: "2026-02-01T00:00:00")
    call_logger.log_call("query", {"q": "b"}, {"hits": 2}, 20.0)

    jan_file = tmp_path / "calls-202601.jsonl"
    feb_file = tmp_path / "calls-202602.jsonl"
    assert jan_file.exists(), "1월 로그 파일이 없음"
    assert feb_file.exists(), "2월 로그 파일이 없음"

    jan_entries = [json.loads(l) for l in jan_file.read_text().splitlines() if l]
    feb_entries = [json.loads(l) for l in feb_file.read_text().splitlines() if l]
    assert len(jan_entries) == 1
    assert len(feb_entries) == 1


def test_redaction(tmp_path, monkeypatch):
    import call_logger

    monkeypatch.setattr(call_logger, "LOG_DIR", tmp_path)
    monkeypatch.setattr(call_logger, "_now", lambda: "2026-01-15T12:00:00")

    result_summary = {
        "basis": [
            {
                "title": "Decision - Use Python",
                "decision_excerpt": "We chose Python because it is easy to use and has many libraries.",
                "rationale_excerpt": "The team agreed Python would accelerate development.",
            }
        ],
        "hits": 1,
    }

    call_logger.log_call("advise", {"question": "which language?"}, result_summary, 50.0)

    assert result_summary["basis"][0]["decision_excerpt"] != "<redacted>"

    log_file = tmp_path / "calls-202601.jsonl"
    entry = json.loads(log_file.read_text().splitlines()[0])

    basis = entry["result"]["basis"][0]
    assert basis["title"] == "Decision - Use Python"
    assert "<redacted" in basis["decision_excerpt"]
    assert "<redacted" in basis["rationale_excerpt"]
