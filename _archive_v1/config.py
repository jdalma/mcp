"""Configuration for vault-decision MCP server."""

import os
from pathlib import Path

VAULT_PATH_ENV = "VAULT_PATH"
VAULT_PATH_DEFAULT = "~/knowledge/memory-palace"

EMBEDDING_MODEL_ENV = "VAULT_EMBEDDING_MODEL"
EMBEDDING_MODEL_DEFAULT = "snunlp/KR-SBERT-V40K-klueNLI-augSTS"

COLLECTION_NAME = "vault_decisions"

INDEX_PATTERNS = [
    "01 Notes/*.md",
    "02 Maps/*.md",
    "03 Sources/*.md",
    "99 Archive/**/*.md",
    "graphify-out/GRAPH_REPORT.md",
    "graphify-out/wiki/*.md",
    "graphify-out/wiki/**/*.md",
]

MAX_RESULTS_DEFAULT = 5

CHROMA_PERSIST_DIR_NAME = ".chroma"


def get_vault_path() -> Path:
    """Return the resolved absolute path to the Obsidian vault."""
    raw = os.environ.get(VAULT_PATH_ENV, VAULT_PATH_DEFAULT)
    return Path(raw).expanduser().resolve()


def get_embedding_model() -> str:
    """Return the sentence-transformer model name for embeddings."""
    return os.environ.get(EMBEDDING_MODEL_ENV, EMBEDDING_MODEL_DEFAULT)


def get_chroma_dir() -> Path:
    """Return the path to the ChromaDB persistence directory."""
    return Path(__file__).parent / CHROMA_PERSIST_DIR_NAME
