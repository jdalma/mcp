# searcher.py
import logging

logger = logging.getLogger(__name__)


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

    lines = [
        f"## Vault Decision Search Results\n",
        f"Query: \"{question}\"",
        f"Found: {len(ids)} relevant records\n",
    ]

    for i, (doc_id, doc, meta, dist) in enumerate(
        zip(ids, documents, metadatas, distances), 1
    ):
        similarity = max(0.0, 1.0 - dist)  # ChromaDB distance → similarity
        title = meta.get("title", doc_id)
        doc_type = meta.get("type", "unknown")
        status = meta.get("status", "unknown")
        created = meta.get("created", "")
        rel_path = meta.get("relative_path", doc_id)
        tags = meta.get("tags", "")

        # 본문에서 처음 300자를 excerpt로
        excerpt = doc[:300].replace("\n", " ").strip()
        if len(doc) > 300:
            excerpt += "..."

        lines.append(f"### {i}. {title} (similarity: {similarity:.2f})")
        lines.append(f"- Path: `{rel_path}`")
        lines.append(f"- Type: {doc_type} | Status: {status}")
        if created:
            lines.append(f"- Created: {created}")
        if tags:
            lines.append(f"- Tags: {tags}")
        lines.append(f"- Excerpt: {excerpt}")
        lines.append("")

    return "\n".join(lines)
