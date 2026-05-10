"""Configuration: 환경변수에서 vault 경로, 인덱스 경로, 임베딩 모델 이름을 읽는다."""

from __future__ import annotations

import os
from pathlib import Path

VAULT_PATH_ENV = "VAULT_PATH"
INDEX_PATH_ENV = "VAULT_DECISION_INDEX"
EMBEDDING_MODEL_ENV = "VAULT_EMBEDDING_MODEL"

DEFAULT_INDEX_PATH = Path.home() / ".cache" / "vault-decision-mcp" / "index.db"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"

INDEX_PATTERNS = [
    "01 Notes/*.md",
    "02 Maps/*.md",
    "03 Sources/*.md",
    "99 Archive/**/*.md",
]


def get_vault_path() -> Path:
    raw = os.environ.get(VAULT_PATH_ENV)
    if not raw:
        raise RuntimeError(f"{VAULT_PATH_ENV} environment variable is required.")
    return Path(raw).expanduser().resolve()


def get_index_path() -> Path:
    raw = os.environ.get(INDEX_PATH_ENV)
    return Path(raw).expanduser().resolve() if raw else DEFAULT_INDEX_PATH


def get_embedding_model() -> str:
    return os.environ.get(EMBEDDING_MODEL_ENV, DEFAULT_EMBEDDING_MODEL)
