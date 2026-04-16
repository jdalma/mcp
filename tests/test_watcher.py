"""Tests for vault file watcher."""

import tempfile
import time
from pathlib import Path


def test_watcher_detects_changes():
    """watcher가 .md 파일 변경을 감지하는지 테스트."""
    from watcher import start_watcher

    triggered = []

    def on_change():
        triggered.append(True)

    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir)
        (vault / "test.md").write_text("initial")

        observer = start_watcher(vault, on_change)
        try:
            # 파일 수정
            time.sleep(0.5)
            (vault / "test.md").write_text("modified")

            # 디바운스 대기 (5초) + 여유
            time.sleep(7)

            assert len(triggered) >= 1
        finally:
            observer.stop()
            observer.join(timeout=5)


def test_watcher_ignores_non_md():
    """watcher가 .md가 아닌 파일은 무시하는지 테스트."""
    from watcher import start_watcher

    triggered = []

    def on_change():
        triggered.append(True)

    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir)

        observer = start_watcher(vault, on_change)
        try:
            time.sleep(0.5)
            (vault / "test.txt").write_text("not markdown")
            (vault / "test.json").write_text("{}")

            time.sleep(7)

            assert len(triggered) == 0
        finally:
            observer.stop()
            observer.join(timeout=5)
