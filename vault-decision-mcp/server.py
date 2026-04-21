# server.py
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from config import (
    COLLECTION_NAME,
    MAX_RESULTS_DEFAULT,
    get_chroma_dir,
    get_embedding_model,
    get_vault_path,
)
from indexer import build_index
from searcher import format_results, search
from tools_extra import get_stats, get_decision_timeline

# MCP 서버는 stdio/HTTP 모두 stdout을 오염시키면 안 된다
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

_collection = None
_observer = None
_index_lock = asyncio.Lock()


def _init_collection():
    """임베딩 모델과 ChromaDB를 초기화하고 collection을 반환한다."""
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    logger.info("Initializing embedding model and ChromaDB...")
    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name=get_embedding_model()
    )
    chroma_client = chromadb.PersistentClient(path=str(get_chroma_dir()))
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    count = build_index(collection)
    logger.info("Initialization complete: indexed %d documents.", count)
    return collection


def _ensure_initialized():
    """Lazily initialize the collection for direct module use and tests."""
    global _collection
    if _collection is None:
        _collection = _init_collection()
    return _collection


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """서버 시작 시 1회 초기화, 종료 시 watcher를 정상 종료한다."""
    global _collection, _observer

    _ensure_initialized()

    loop = asyncio.get_running_loop()

    if _observer is None:
        try:
            from watcher import start_watcher

            async def _reindex():
                async with _index_lock:
                    build_index(_collection)

            def _reindex_sync():
                asyncio.run_coroutine_threadsafe(_reindex(), loop)

            _observer = start_watcher(get_vault_path(), _reindex_sync)
        except Exception as e:
            logger.warning("Failed to start vault watcher: %s", e)

    try:
        yield
    finally:
        obs, _observer = _observer, None
        if obs is not None:
            logger.info("Stopping vault watcher...")
            obs.stop()
            obs.join()
            logger.info("Vault watcher stopped.")


mcp = FastMCP(
    "vault-decision",
    instructions=(
        "Vault Decision Advisory MCP Server. "
        "Searches the user's personal knowledge vault for past decisions, "
        "ADRs, and technical notes to provide grounded decision advice. "
        "Use the 'query' tool to find relevant prior decisions."
    ),
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_PORT", "8765")),
    lifespan=lifespan,
)


@mcp.tool()
async def query(question: str, max_results: int = MAX_RESULTS_DEFAULT) -> str:
    """vault의 Decision/Note를 semantic 검색하여 관련 기록을 반환한다.

    Args:
        question: 의사결정 질문 또는 검색 키워드
        max_results: 반환할 최대 결과 수 (기본 5)
    """
    results = search(_ensure_initialized(), question, max_results)
    return format_results(question, results)


@mcp.tool()
async def list_decisions() -> str:
    """vault의 모든 Decision 파일 목록과 메타데이터를 반환한다."""
    all_docs = _ensure_initialized().get(
        where={"type": "decision"},
        include=["metadatas"],
    )

    if not all_docs["ids"]:
        return "No decision documents found in vault."

    lines = ["## Vault Decision List\n"]
    for doc_id, meta in zip(all_docs["ids"], all_docs["metadatas"]):
        title = meta.get("title", doc_id)
        status = meta.get("status", "")
        created = meta.get("created", "")
        lines.append(f"- **{title}** ({status}, {created}) — `{doc_id}`")

    lines.append(f"\nTotal: {len(all_docs['ids'])} decisions")
    return "\n".join(lines)


@mcp.tool()
async def read_decision(file_name: str) -> str:
    """특정 vault 파일의 전체 내용을 반환한다.

    Args:
        file_name: 파일명 (예: "Decision - Agent Teams 채택") 또는 상대경로
    """
    vault = get_vault_path()

    candidate = vault / file_name
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")

    candidate_md = vault / f"{file_name}.md"
    if candidate_md.exists():
        return candidate_md.read_text(encoding="utf-8")

    for f in (vault / "01 Notes").glob("*.md"):
        if file_name.lower() in f.stem.lower():
            return f.read_text(encoding="utf-8")

    return f"File not found: {file_name}"


@mcp.tool()
async def reindex(force: bool = False) -> str:
    """vault 파일이 변경된 후 embedding 인덱스를 재구축한다.

    Args:
        force: True면 전체 리빌드, False면 증분 업데이트
    """
    async with _index_lock:
        count = build_index(_ensure_initialized(), force=force)
    return f"Reindex complete. {count} documents indexed."


@mcp.tool()
async def stats() -> str:
    """인덱스 상태를 반환한다 (문서 수, 타입별 분포, 상태별 분포)."""
    return get_stats(_ensure_initialized())


@mcp.tool()
async def decision_timeline() -> str:
    """시간순으로 Decision 이력을 반환한다."""
    return get_decision_timeline(_ensure_initialized())


def main():
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
