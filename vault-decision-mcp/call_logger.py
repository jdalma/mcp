"""Tool 호출 로거 — JSONL 형식으로 호출 원인과 결과를 기록한다."""

import json
import time
from pathlib import Path

LOG_PATH = Path.home() / ".vault-decision-mcp" / "calls.jsonl"


def log_call(tool: str, inputs: dict, result_summary: dict, elapsed_ms: float):
    """단일 tool 호출을 JSONL로 기록한다.

    Args:
        tool: tool 이름 (예: "query")
        inputs: tool 입력 파라미터
        result_summary: 결과 요약 (tool마다 다름)
        elapsed_ms: 소요 시간 (밀리초)
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": tool,
        "inputs": inputs,
        "result": result_summary,
        "elapsed_ms": round(elapsed_ms, 1),
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
