# server.py
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from config import (
    COLLECTION_NAME,
    MAX_RESULTS_DEFAULT,
    get_chroma_dir,
    get_daemon_host,
    get_daemon_port,
    get_embedding_model,
    get_vault_path,
)
from indexer import build_index
from searcher import format_results, search
from tools_extra import get_stats, get_decision_timeline

# MCP 서버는 stdio 통신이므로 stdout을 오염시키면 안 된다
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Lazy initialization ---
_collection = None
_initialized = False


def _ensure_initialized():
    """첫 tool 호출 시에만 embedding 모델과 ChromaDB를 초기화한다."""
    global _collection, _initialized
    if _initialized:
        return

    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    logger.info("Initializing embedding model and ChromaDB...")
    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name=get_embedding_model()
    )
    chroma_client = chromadb.PersistentClient(path=str(get_chroma_dir()))
    _collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    count = build_index(_collection)
    logger.info("Initialization complete: indexed %d documents.", count)

    # vault 파일 감시 시작 (변경 시 자동 증분 인덱싱)
    try:
        from watcher import start_watcher
        start_watcher(get_vault_path(), lambda: build_index(_collection))
    except Exception as e:
        logger.warning("Failed to start vault watcher: %s", e)

    _initialized = True


# --- MCP 서버 (즉시 생성, handshake 지연 없음) ---
mcp = FastMCP(
    "vault-decision",
    instructions=(
        "Vault Decision Advisory MCP Server. "
        "Searches the user's personal knowledge vault for past decisions, "
        "ADRs, and technical notes to provide grounded decision advice. "
        "Use the 'query' tool to find relevant prior decisions."
    ),
)


@mcp.tool()
async def query(question: str, max_results: int = MAX_RESULTS_DEFAULT) -> str:
    """vault의 Decision/Note를 semantic 검색하여 관련 기록을 반환한다.

    Args:
        question: 의사결정 질문 또는 검색 키워드
        max_results: 반환할 최대 결과 수 (기본 5)
    """
    _ensure_initialized()
    results = search(_collection, question, max_results)
    return format_results(question, results)


@mcp.tool()
async def list_decisions() -> str:
    """vault의 모든 Decision 파일 목록과 메타데이터를 반환한다."""
    _ensure_initialized()
    all_docs = _collection.get(
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

    # 상대경로로 직접 찾기
    candidate = vault / file_name
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")

    # .md 확장자 추가
    candidate_md = vault / f"{file_name}.md"
    if candidate_md.exists():
        return candidate_md.read_text(encoding="utf-8")

    # 01 Notes/ 하위에서 찾기
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
    _ensure_initialized()
    count = build_index(_collection, force=force)
    return f"Reindex complete. {count} documents indexed."


@mcp.tool()
async def stats() -> str:
    """인덱스 상태를 반환한다 (문서 수, 타입별 분포, 상태별 분포)."""
    _ensure_initialized()
    return get_stats(_collection)


@mcp.tool()
async def decision_timeline() -> str:
    """시간순으로 Decision 이력을 반환한다."""
    _ensure_initialized()
    return get_decision_timeline(_collection)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="vault-decision MCP server")
    parser.add_argument(
        "--daemon", action="store_true",
        help="Run as HTTP daemon (streamable-http) instead of stdio",
    )
    parser.add_argument("--host", default=None, help="Daemon host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Daemon port (default: 8741)")
    args = parser.parse_args()

    if args.daemon:
        import uvicorn

        host = args.host or get_daemon_host()
        port = args.port or get_daemon_port()

        # 데몬 모드: 시작 시 즉시 초기화 (lazy init 대신)
        _ensure_initialized()
        logger.info("Starting daemon on %s:%d", host, port)

        app = mcp.streamable_http_app()
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
