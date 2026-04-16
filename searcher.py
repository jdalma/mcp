# searcher.py
import logging

logger = logging.getLogger(__name__)

# 타입별 부스팅 가중치
TYPE_BOOST = {
    "decision": 0.15,
    "note": 0.0,
    "unknown": 0.0,
}

# status별 부스팅
STATUS_BOOST = {
    "decided": 0.05,
    "confirmed": 0.05,
    "draft": -0.05,
}

# 타입별 prefix
TYPE_PREFIX = {
    "decision": "\U0001f537",  # 🔷
    "note": "\U0001f4dd",      # 📝
}


def search(collection, question: str, max_results: int = 5) -> dict:
    """ChromaDB collection에서 question과 유사한 문서를 검색한다."""
    results = collection.query(
        query_texts=[question],
        n_results=min(max_results, collection.count() or 1),
        include=["documents", "metadatas", "distances"],
    )
    return results


def format_results(question: str, query_results: dict) -> str:
    """검색 결과를 Claude가 읽기 좋은 텍스트로 포맷한다."""
    ids = query_results["ids"][0] if query_results["ids"] else []
    documents = query_results["documents"][0] if query_results["documents"] else []
    metadatas = query_results["metadatas"][0] if query_results["metadatas"] else []
    distances = query_results["distances"][0] if query_results["distances"] else []

    if not ids:
        return (
            f"## Vault Decision Search Results\n\n"
            f"Query: \"{question}\"\n\n"
            f"No relevant records found in vault."
        )

    # 부스팅된 유사도 계산 및 재정렬
    entries = []
    for doc_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
        similarity = max(0.0, 1.0 - dist)
        doc_type = meta.get("type", "unknown")
        status = meta.get("status", "unknown")
        type_boost = TYPE_BOOST.get(doc_type, 0.0)
        status_boost = STATUS_BOOST.get(status, 0.0)
        boosted_similarity = min(1.0, similarity + type_boost + status_boost)
        entries.append((doc_id, doc, meta, boosted_similarity))

    entries.sort(key=lambda e: e[3], reverse=True)

    lines = [
        f"## Vault Decision Search Results\n",
        f"Query: \"{question}\"",
        f"Found: {len(ids)} relevant records\n",
    ]

    for i, (doc_id, doc, meta, boosted_sim) in enumerate(entries, 1):
        title = meta.get("title", doc_id)
        doc_type = meta.get("type", "unknown")
        status = meta.get("status", "unknown")
        created = meta.get("created", "")
        rel_path = meta.get("relative_path", doc_id)
        tags = meta.get("tags", "")
        prefix = TYPE_PREFIX.get(doc_type, "")

        # 본문에서 처음 300자를 excerpt로
        excerpt = doc[:300].replace("\n", " ").strip()
        if len(doc) > 300:
            excerpt += "..."

        display_title = f"{prefix} {title}" if prefix else title
        lines.append(f"### {i}. {display_title} (similarity: {boosted_sim:.2f})")
        lines.append(f"- Path: `{rel_path}`")
        lines.append(f"- Type: {doc_type} | Status: {status}")
        if created:
            lines.append(f"- Created: {created}")
        if tags:
            lines.append(f"- Tags: {tags}")
        lines.append(f"- Excerpt: {excerpt}")
        lines.append("")

    return "\n".join(lines)
