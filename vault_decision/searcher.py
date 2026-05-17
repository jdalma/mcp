"""BM25 (FTS5) + bge-m3 코사인 유사도 → RRF 융합 검색."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from typing import Any

import numpy as np

from vault_decision.config import get_index_path
from vault_decision.indexer import get_embedder, open_index

logger = logging.getLogger(__name__)

RRF_K = 60
DEFAULT_FETCH_K = 30

_FTS_SPECIAL_RE = re.compile(r'[\"\*\:\(\)\-]+|\bAND\b|\bOR\b|\bNOT\b|\bNEAR\b')


def sanitize_fts_query(question: str) -> str:
    """자연어 질문 → FTS5 MATCH 안전 입력으로 변환.

    FTS5의 묵시적 연산자는 AND이므로, 자연어 질문의 단어 모두를 강제하면
    recall이 무너진다. 따라서 OR로 결합한다 — 한 단어라도 일치하는 문서를
    BM25가 점수로 정렬한다.

    Special token 제거 → 토큰화 → double-quote wrap → " OR " join.
    빈 결과면 "" 반환 (호출 측에서 BM25 skip).
    """
    cleaned = _FTS_SPECIAL_RE.sub(" ", question)
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def bm25_search(
    conn: sqlite3.Connection, query: str, k: int = DEFAULT_FETCH_K
) -> list[tuple[int, float]]:
    """FTS5 BM25 검색. (rowid, raw_bm25_score) 리스트."""
    sanitized = sanitize_fts_query(query)
    if not sanitized:
        return []
    try:
        rows = conn.execute(
            """
            SELECT rowid, bm25(docs_fts, 5.0, 3.0, 1.0) AS score
            FROM docs_fts
            WHERE docs_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (sanitized, k),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("BM25 search failed: %s", e)
        return []
    # bm25()는 음수 점수(작을수록 좋음). 호출 측은 rank만 쓰지만 raw도 보존.
    return [(int(rowid), float(score)) for rowid, score in rows]


def embedding_search(
    conn: sqlite3.Connection, query_vec: np.ndarray, k: int = DEFAULT_FETCH_K
) -> list[tuple[int, float]]:
    """모든 docs.embedding과 코사인 유사도(이미 L2 정규화됨 → dot product). top-k."""
    rows = conn.execute(
        "SELECT rowid, embedding FROM docs WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    rowids = np.array([r[0] for r in rows], dtype=np.int64)
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    scores = matrix @ query_vec
    if len(scores) <= k:
        order = np.argsort(-scores)
    else:
        top_idx = np.argpartition(-scores, k)[:k]
        order = top_idx[np.argsort(-scores[top_idx])]
    return [(int(rowids[i]), float(scores[i])) for i in order]


def rrf_fuse(
    rankings: list[list[int]], k: int = RRF_K
) -> dict[int, float]:
    """rowid 리스트들의 reciprocal rank fusion. {rowid: rrf_score}."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, rowid in enumerate(ranking, start=1):
            fused[rowid] = fused.get(rowid, 0.0) + 1.0 / (k + rank)
    return fused


def _row_to_result(
    row: sqlite3.Row,
    score_bm25: float | None,
    rank_bm25: int | None,
    score_emb: float | None,
    rank_emb: int | None,
    score_rrf: float,
) -> dict[str, Any]:
    try:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}
    return {
        "path": row["path"],
        "title": row["title"],
        "type": row["type"],
        "canonical": bool(row["canonical"]),
        "path_role": row["path_role"] or "unknown",
        "context": row["context"],
        "body": row["body"],
        "score_bm25": score_bm25,
        "rank_bm25": rank_bm25,
        "score_embedding": score_emb,
        "rank_embedding": rank_emb,
        "score_rrf": score_rrf,
        "metadata": metadata,
    }


def search(
    conn: sqlite3.Connection,
    question: str,
    *,
    max_results: int = 15,
    fetch_k: int = DEFAULT_FETCH_K,
) -> list[dict[str, Any]]:
    """BM25 + 임베딩 → RRF 융합 → top-N. 점수 분해 포함 (NFR-8)."""
    bm25_hits = bm25_search(conn, question, k=fetch_k)
    bm25_scores = {rid: sc for rid, sc in bm25_hits}
    bm25_ranks = {rid: i + 1 for i, (rid, _) in enumerate(bm25_hits)}

    model = get_embedder()
    qv = model.encode([question], show_progress_bar=False)
    qv = np.asarray(qv, dtype=np.float32)[0]
    norm = np.linalg.norm(qv)
    if norm > 0:
        qv = qv / norm

    emb_hits = embedding_search(conn, qv, k=fetch_k)
    emb_scores = {rid: sc for rid, sc in emb_hits}
    emb_ranks = {rid: i + 1 for i, (rid, _) in enumerate(emb_hits)}

    fused = rrf_fuse([[rid for rid, _ in bm25_hits], [rid for rid, _ in emb_hits]])
    if not fused:
        return []

    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:max_results]
    rowids = [rid for rid, _ in ordered]
    placeholders = ",".join(["?"] * len(rowids))
    conn.row_factory = sqlite3.Row
    rows = {
        row["rowid"]: row
        for row in conn.execute(
            f"SELECT rowid, * FROM docs WHERE rowid IN ({placeholders})", rowids
        ).fetchall()
    }
    conn.row_factory = None

    results: list[dict[str, Any]] = []
    for rid, rrf in ordered:
        row = rows.get(rid)
        if row is None:
            continue
        results.append(
            _row_to_result(
                row,
                score_bm25=bm25_scores.get(rid),
                rank_bm25=bm25_ranks.get(rid),
                score_emb=emb_scores.get(rid),
                rank_emb=emb_ranks.get(rid),
                score_rrf=rrf,
            )
        )
    return results


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser(prog="vault_decision.searcher")
    parser.add_argument("question", help="검색할 자연어 질문")
    parser.add_argument("-k", "--max-results", type=int, default=5)
    args = parser.parse_args()

    conn = open_index(get_index_path())
    try:
        results = search(conn, args.question, max_results=args.max_results)
    finally:
        conn.close()

    if not results:
        print("(no results)")
        sys.exit(0)

    for i, r in enumerate(results, 1):
        rb = r["rank_bm25"]
        re_ = r["rank_embedding"]
        print(
            f"#{i} {r['title']}  "
            f"[role={r['path_role']} type={r['type']} canonical={r['canonical']}]"
        )
        print(f"     path={r['path']}")
        print(
            f"     rrf={r['score_rrf']:.4f}  "
            f"bm25_rank={rb if rb is not None else '-'}  "
            f"emb_rank={re_ if re_ is not None else '-'}  "
            f"emb_cosine={r['score_embedding']:.3f}"
            if r["score_embedding"] is not None
            else f"     rrf={r['score_rrf']:.4f}  bm25_rank={rb}  emb_rank=-"
        )
        if r["context"]:
            print(f"     context: {r['context']}")
        print()


if __name__ == "__main__":
    main()
