"""Vault file watcher for automatic re-indexing."""

import logging
import threading
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)

# 디바운스: 여러 변경이 연속 발생할 때 한 번만 인덱싱
DEBOUNCE_SECONDS = 5.0


class VaultChangeHandler(FileSystemEventHandler):
    """vault의 .md 파일 변경을 감지하여 리인덱싱을 트리거한다."""

    def __init__(self, reindex_callback):
        super().__init__()
        self._callback = reindex_callback
        self._timer = None
        self._lock = threading.Lock()

    def _schedule_reindex(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._do_reindex)
            self._timer.daemon = True
            self._timer.start()

    def _do_reindex(self):
        try:
            logger.info("Vault change detected, triggering incremental reindex...")
            self._callback()
            logger.info("Auto-reindex complete.")
        except Exception as e:
            logger.error("Auto-reindex failed: %s", e)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._schedule_reindex()

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._schedule_reindex()

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._schedule_reindex()


def start_watcher(vault_path: Path, reindex_callback) -> Observer:
    """vault 디렉토리 감시를 시작한다. 별도 데몬 스레드로 실행.

    Args:
        vault_path: 감시할 vault 디렉토리
        reindex_callback: 변경 감지 시 호출할 콜백 (인자 없음)

    Returns:
        Observer 인스턴스 (stop() 호출로 중지 가능)
    """
    handler = VaultChangeHandler(reindex_callback)
    observer = Observer()
    observer.schedule(handler, str(vault_path), recursive=True)
    observer.daemon = True
    observer.start()
    logger.info("Vault watcher started: %s", vault_path)
    return observer
