# searcher.py
import logging

logger = logging.getLogger(__name__)

AUTHORITY_SIMILARITY_THRESHOLD = 0.35

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

PATH_ROLE_BOOST = {
    "active_decision": 0.05,
    "active_note": 0.0,
    "moc": -0.02,
    "source": -0.03,
    "archive": -0.15,
    "graph_sidecar": -0.08,
}


def search(collection, question: str, max_results: int = 5, overfetch: int | None = None) -> dict:
    """ChromaDB collection에서 question과 유사한 문서를 검색한다."""
    count = collection.count() or 1
    n_results = min(overfetch or max(max_results * 4, 20), count)
    results = collection.query(
        query_texts=[question],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    return results


def rank_results(query_results: dict, max_results: int | None = None) -> list[dict]:
    """Return search entries with semantic-threshold-aware boosts applied."""
    ids = query_results["ids"][0] if query_results["ids"] else []
    documents = query_results["documents"][0] if query_results["documents"] else []
    metadatas = query_results["metadatas"][0] if query_results["metadatas"] else []
    distances = query_results["distances"][0] if query_results["distances"] else []

    entries = []
    for doc_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
        similarity = max(0.0, 1.0 - dist)
        doc_type = meta.get("type", "unknown")
        status = meta.get("status", "unknown")
        path_role = meta.get("path_role", "unknown")

        boosted_similarity = similarity
        if similarity >= AUTHORITY_SIMILARITY_THRESHOLD:
            boosted_similarity += TYPE_BOOST.get(doc_type, 0.0)
            boosted_similarity += STATUS_BOOST.get(status, 0.0)
            boosted_similarity += PATH_ROLE_BOOST.get(path_role, 0.0)

        entries.append(
            {
                "id": doc_id,
                "document": doc,
                "metadata": meta,
                "similarity": similarity,
                "boosted_similarity": min(1.0, boosted_similarity),
                "distance": dist,
            }
        )

    entries.sort(key=lambda entry: entry["boosted_similarity"], reverse=True)
    if max_results is not None:
        return entries[:max_results]
    return entries


def format_results(question: str, query_results: dict, max_results: int = 5) -> str:
    """검색 결과를 Claude가 읽기 좋은 텍스트로 포맷한다."""
    entries = rank_results(query_results, max_results=max_results)

    if not entries:
        return (
            f"## Vault Decision Search Results\n\n"
            f"Query: \"{question}\"\n\n"
            f"No relevant records found in vault."
        )

    lines = [
        f"## Vault Decision Search Results\n",
        f"Query: \"{question}\"",
        f"Found: {len(entries)} relevant records\n",
    ]

    for i, entry in enumerate(entries, 1):
        doc_id = entry["id"]
        doc = entry["document"]
        meta = entry["metadata"]
        boosted_sim = entry["boosted_similarity"]
        title = meta.get("title", doc_id)
        doc_type = meta.get("type", "unknown")
        status = meta.get("status", "unknown")
        path_role = meta.get("path_role", "unknown")
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
        lines.append(f"- Type: {doc_type} | Status: {status} | Path role: {path_role}")
        if created:
            lines.append(f"- Created: {created}")
        if tags:
            lines.append(f"- Tags: {tags}")
        lines.append(f"- Excerpt: {excerpt}")
        lines.append("")

    return "\n".join(lines)
