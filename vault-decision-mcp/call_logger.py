"""Tool 호출 로거 — JSONL 형식으로 호출 원인과 결과를 기록한다."""

import copy
import json
import time
from pathlib import Path

LOG_DIR = Path.home() / ".vault-decision-mcp"

_REDACT_FIELDS = ("decision_excerpt", "rationale_excerpt")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _log_path() -> Path:
    month = _now()[:7].replace("-", "")
    return LOG_DIR / f"calls-{month}.jsonl"


def _redact(result: dict) -> dict:
    result = copy.deepcopy(result)
    for item in result.get("basis", []):
        for field in _REDACT_FIELDS:
            if field in item:
                original_len = len(item[field])
                item[field] = f"<redacted: {original_len} chars>"
    return result


def log_call(tool: str, inputs: dict, result_summary: dict, elapsed_ms: float):
    """단일 tool 호출을 JSONL로 기록한다.

    Args:
        tool: tool 이름 (예: "query")
        inputs: tool 입력 파라미터
        result_summary: 결과 요약 (tool마다 다름)
        elapsed_ms: 소요 시간 (밀리초)
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _now(),
        "tool": tool,
        "inputs": inputs,
        "result": _redact(result_summary),
        "elapsed_ms": round(elapsed_ms, 1),
    }
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
