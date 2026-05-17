"""vault-decision MCP server v2 — 5 tools (stdio transport)."""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from vault_decision.advisor import advise as advise_fn
from vault_decision.config import get_index_path, get_vault_path
from vault_decision.indexer import build_index, open_index
from vault_decision.indexer import stats as stats_fn
from vault_decision.lint import lint as lint_fn
from vault_decision.searcher import search as search_fn

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("vault-decision")

_conn = None


def _get_conn():
    """모듈 글로벌 SQLite 연결. stdio 단일 프로세스 가정 (NFR-1)."""
    global _conn
    if _conn is None:
        _conn = open_index(get_index_path())
        _ensure_indexed()
    return _conn


def _ensure_indexed() -> None:
    """첫 기동 시 인덱스가 비어있으면 build (lazy). 이미 있으면 skip."""
    s = stats_fn(_conn)
    if s["total"] == 0:
        logger.info("Index empty — building from %s", get_vault_path())
        build_index(_conn, get_vault_path())


def _render_query_markdown(hits: list[dict]) -> str:
    """검색 결과 dict 리스트를 사람이 읽을 마크다운으로."""
    if not hits:
        return "(no results)"
    lines: list[str] = []
    for i, h in enumerate(hits, 1):
        lines.append(f"## #{i} {h['title']}")
        lines.append(f"- path: `{h['path']}`")
        lines.append(
            f"- role: {h['path_role']}, type: {h['type']}, reviewed: {h['human_reviewed']}"
        )
        rb = h["rank_bm25"] if h["rank_bm25"] is not None else "-"
        re_ = h["rank_embedding"] if h["rank_embedding"] is not None else "-"
        lines.append(
            f"- rrf: {h['score_rrf']:.4f}, bm25_rank: {rb}, emb_rank: {re_}"
        )
        if h["context"]:
            lines.append(f"- context: {h['context']}")
        excerpt = (h["body"] or "")[:300].replace("\n", " ")
        lines.append(f"\n> {excerpt}...\n")
    return "\n".join(lines)


@mcp.tool()
def advise(question: str, max_results: int = 5) -> dict:
    """질문에 대해 vault의 권위 결정을 찾아 분류하고 추천 액션을 산출."""
    return advise_fn(_get_conn(), question, max_results=max_results)


@mcp.tool()
def query(question: str, max_results: int = 5) -> str:
    """검색 결과만 마크다운으로 반환 (권위 판정 없이 raw)."""
    hits = search_fn(_get_conn(), question, max_results=max_results)
    return _render_query_markdown(hits)


@mcp.tool()
def read_decision(file_name: str) -> str:
    """Vault에서 파일 본문을 반환. 없으면 'File not found: ...' 문자열 (예외 X).

    parent_plan NFR-2: path-escape 가드 없음. 단일 사용자 stdio 가정.
    """
    _ = _get_conn()  # lazy init 보장
    vault = get_vault_path()
    full = vault / file_name
    if not full.exists():
        return f"File not found: {file_name}"
    return full.read_text(encoding="utf-8")


@mcp.tool()
def lint() -> dict:
    """3룰(asymmetric_conflict / stale_decision / superseded_dangling) 위반 보고."""
    return lint_fn(_get_conn())


@mcp.tool()
def reindex() -> str:
    """Vault 전체를 다시 인덱싱 (force=True)."""
    n = build_index(_get_conn(), get_vault_path(), force=True)
    return f"Indexed {n} documents"


def main() -> None:
    logger.info("vault-decision-mcp v2 starting on stdio (5 tools)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
