# server.py
import logging
import sys
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from mcp.server.fastmcp import FastMCP

from config import (
    COLLECTION_NAME,
    MAX_RESULTS_DEFAULT,
    get_chroma_dir,
    get_embedding_model,
    get_vault_path,
)
from indexer import build_index, collect_vault_files, parse_markdown
from searcher import format_results, search

# MCP 서버는 stdio 통신이므로 stdout을 오염시키면 안 된다
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Embedding + ChromaDB 초기화 ---

_embedding_fn = SentenceTransformerEmbeddingFunction(
    model_name=get_embedding_model()
)

_chroma_client = chromadb.PersistentClient(path=str(get_chroma_dir()))

_collection = _chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=_embedding_fn,
)

# 서버 시작 시 인덱스 구축 (이미 인덱싱되어 있으면 빠르게 통과)
_indexed_count = build_index(_collection)
logger.info("Server startup: indexed %d documents.", _indexed_count)

# --- MCP 서버 ---

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
    results = search(_collection, question, max_results)
    return format_results(question, results)


@mcp.tool()
async def list_decisions() -> str:
    """vault의 모든 Decision 파일 목록과 메타데이터를 반환한다."""
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
    count = build_index(_collection, force=force)
    return f"Reindex complete. {count} documents indexed."


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
