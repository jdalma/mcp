"""Additional MCP tool implementations for vault-decision server."""

from config import get_vault_path


def get_stats(collection) -> str:
    """인덱스 상태를 반환한다."""
    all_docs = collection.get(include=["metadatas"])
    total = len(all_docs["ids"])

    if total == 0:
        return "## Vault Index Stats\n\nNo documents indexed."

    # 타입별 분포
    type_counts = {}
    status_counts = {}
    for meta in all_docs["metadatas"]:
        doc_type = meta.get("type", "unknown")
        type_counts[doc_type] = type_counts.get(doc_type, 0) + 1
        status = meta.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    lines = [
        "## Vault Index Stats\n",
        f"Total documents: {total}\n",
        "### By Type",
    ]
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {t}: {count}")

    lines.append("\n### By Status")
    for s, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {s}: {count}")

    return "\n".join(lines)


def get_decision_timeline(collection) -> str:
    """시간순으로 Decision 이력을 반환한다."""
    all_docs = collection.get(
        where={"type": "decision"},
        include=["metadatas"],
    )

    if not all_docs["ids"]:
        return "## Decision Timeline\n\nNo decisions found."

    # created 기준 정렬
    entries = list(zip(all_docs["ids"], all_docs["metadatas"]))
    entries.sort(key=lambda x: x[1].get("created", ""), reverse=True)

    lines = ["## Decision Timeline\n"]
    for doc_id, meta in entries:
        title = meta.get("title", doc_id)
        created = meta.get("created", "unknown")
        status = meta.get("status", "")
        lines.append(f"- **{created}** — {title} ({status})")

    lines.append(f"\nTotal: {len(entries)} decisions")
    return "\n".join(lines)
