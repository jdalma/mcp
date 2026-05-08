"""Vault file parsing and ChromaDB indexing."""

import hashlib
import logging
from pathlib import Path

import yaml

from config import INDEX_PATTERNS, get_vault_path

logger = logging.getLogger(__name__)

# build_index 실행 후 비대칭 conflicts_with 선언 목록 (모듈 글로벌)
_asymmetric_conflicts: list[str] = []


def get_asymmetric_conflicts() -> list[str]:
    """마지막 build_index에서 감지된 비대칭 conflicts_with 경로 목록을 반환한다."""
    return list(_asymmetric_conflicts)


def _metadata_list(value) -> str:
    """Convert YAML scalar/list metadata to Chroma-friendly text."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _has_decision_candidates(value) -> bool:
    return isinstance(value, list) and len(value) > 0


def infer_path_role(relative_path: str, metadata: dict) -> str:
    """Infer the vault role from path and frontmatter."""
    doc_type = metadata.get("type", "unknown")
    path = relative_path.replace("\\", "/")
    name = Path(path).name

    if path.startswith("00 Inbox/"):
        return "inbox_staging"
    if path.startswith("01 Notes/") and doc_type == "decision" and name.startswith("Decision - "):
        return "active_decision"
    if path.startswith("01 Notes/"):
        return "active_note"
    if path.startswith("02 Maps/"):
        return "moc"
    if path.startswith("03 Sources/"):
        return "source"
    if path.startswith("99 Archive/"):
        return "archive"
    if path.startswith("graphify-out/"):
        return "graph_sidecar"
    if path.startswith("docs/plans/"):
        return "planning"
    return "unknown"


def parse_markdown(text: str, source: str | None = None) -> tuple[dict, str]:
    """마크다운 파일에서 YAML frontmatter와 body를 분리한다.

    YAML 파싱 실패 시 빈 dict로 fallback하지만 경고 로그를 남긴다.
    """
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        logger.warning(
            "YAML frontmatter parse failed%s: %s",
            f" for {source}" if source else "",
            e,
        )
        meta = {}

    if not isinstance(meta, dict):
        logger.warning(
            "YAML frontmatter is not a mapping%s; ignoring",
            f" for {source}" if source else "",
        )
        meta = {}

    body = parts[2].strip()
    return meta, body


def collect_vault_files(vault_path: Path | None = None) -> list[Path]:
    """INDEX_PATTERNS에 매칭되는 vault 파일을 수집한다.

    vault root 밖을 가리키는 symlink는 제외한다 (경로 탈출 방지).
    """
    vault = vault_path or get_vault_path()
    vault_root = vault.resolve()

    files: list[Path] = []
    for pattern in INDEX_PATTERNS:
        matched = sorted(vault.glob(pattern))
        files.extend(matched)

    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        try:
            resolved = f.resolve(strict=False)
            resolved.relative_to(vault_root)
        except ValueError:
            logger.warning("Skipping path that escapes vault root: %s", f)
            continue
        unique.append(f)
    return unique


def prepare_document(
    file_path: Path,
    metadata: dict,
    body: str,
    vault_path: Path | None = None,
) -> dict:
    """ChromaDB에 저장할 document dict를 구성한다."""
    vault = vault_path or get_vault_path()
    try:
        relative = str(file_path.relative_to(vault))
    except ValueError:
        relative = str(file_path)

    title = file_path.stem
    doc_type = metadata.get("type", "unknown")
    status = metadata.get("status", "unknown")
    tags = metadata.get("tags", [])
    created = metadata.get("created", "")
    updated = metadata.get("updated", "")
    decided_on = metadata.get("decided_on", "")
    revisit_when = metadata.get("revisit_when", "")
    decision_status = metadata.get("decision_status", "")
    mocs = metadata.get("mocs", [])
    sources = metadata.get("sources", [])
    decision_candidates = metadata.get("decision_candidates", [])
    conflicts_with = metadata.get("conflicts_with", "")
    path_role = infer_path_role(relative, metadata)
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    context = str(metadata.get("context", ""))

    # 검색에 사용할 텍스트: 제목 + 메타데이터 요약 + frontmatter context + 본문
    search_text = (
        f"# {title}\n"
        f"type: {doc_type} | status: {status} | "
        f"tags: {', '.join(str(t) for t in tags) if isinstance(tags, list) else ''}\n"
        + (f"context: {context}\n" if context else "")
        + f"\n{body}"
    )

    return {
        "id": relative,
        "document": search_text,
        "metadata": {
            "type": doc_type,
            "status": str(status),
            "title": title,
            "tags": _metadata_list(tags),
            "created": str(created),
            "updated": str(updated),
            "decided_on": str(decided_on),
            "revisit_when": str(revisit_when),
            "decision_status": str(decision_status),
            "mocs": _metadata_list(mocs),
            "sources": _metadata_list(sources),
            "has_decision_candidates": _has_decision_candidates(decision_candidates),
            "conflicts_with": _metadata_list(conflicts_with),
            "path_role": path_role,
            "content_hash": content_hash,
            "file_path": str(file_path),
            "relative_path": relative,
        },
    }


def build_index(
    collection,
    vault_path: Path | None = None,
    force: bool = False,
) -> int:
    """vault 파일을 파싱하여 ChromaDB collection에 인덱싱한다.

    Args:
        force: True면 전체 리빌드, False면 증분 업데이트

    Returns:
        인덱싱된 문서 수.
    """
    vault = vault_path or get_vault_path()
    files = collect_vault_files(vault)
    if not files:
        logger.warning("No vault files found to index.")
        return 0

    if force:
        # 전체 리빌드: 기존 인덱스 삭제
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

    # 현재 파일의 mtime 수집
    current_files: dict[str, str] = {}  # relative_path -> mtime_str
    for file_path in files:
        try:
            mtime = file_path.stat().st_mtime
            rel = str(file_path.relative_to(vault))
            current_files[rel] = str(mtime)
        except Exception:
            continue

    if not force:
        # 기존 인덱스에서 mtime 비교
        existing = collection.get(include=["metadatas"])
        existing_mtimes: dict[str, str] = {}
        for doc_id, meta in zip(existing["ids"], existing["metadatas"]):
            existing_mtimes[doc_id] = meta.get("mtime", "")

        # 삭제된 파일 제거
        deleted = set(existing_mtimes.keys()) - set(current_files.keys())
        if deleted:
            collection.delete(ids=list(deleted))

        # 변경/추가된 파일만 필터링
        files_to_index = []
        for file_path in files:
            rel = str(file_path.relative_to(vault))
            current_mtime = current_files.get(rel, "")
            if rel not in existing_mtimes or existing_mtimes[rel] != current_mtime:
                files_to_index.append(file_path)

        if not files_to_index and not deleted:
            logger.info("Index is up-to-date. No changes detected.")
            return collection.count()
    else:
        files_to_index = files

    # 인덱싱
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for file_path in files_to_index:
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read %s: %s", file_path, e)
            continue

        meta, body = parse_markdown(text, source=str(file_path))
        doc = prepare_document(file_path, meta, body, vault_path=vault)
        rel = doc["id"]
        doc["metadata"]["mtime"] = current_files.get(rel, "")
        ids.append(doc["id"])
        documents.append(doc["document"])
        metadatas.append(doc["metadata"])

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    logger.info("Indexed %d documents (%d updated).", collection.count(), len(ids))

    # 양방향 conflicts_with 무결성 검증
    _check_asymmetric_conflicts(collection)

    return collection.count()


def _check_asymmetric_conflicts(collection) -> None:
    """전체 인덱스에서 conflicts_with 양방향 선언이 누락된 항목을 감지한다."""
    global _asymmetric_conflicts

    all_docs = collection.get(include=["metadatas"])
    # title → relative_path 매핑
    title_to_path: dict[str, str] = {}
    for doc_id, meta in zip(all_docs["ids"], all_docs["metadatas"]):
        title = meta.get("title", "")
        if title:
            title_to_path[title] = doc_id

    # relative_path → conflicts_with 텍스트
    path_to_conflicts: dict[str, str] = {}
    for doc_id, meta in zip(all_docs["ids"], all_docs["metadatas"]):
        cw = meta.get("conflicts_with", "")
        if cw:
            path_to_conflicts[doc_id] = cw

    asymmetric: list[str] = []
    for path, conflicts_text in path_to_conflicts.items():
        declaring_title = None
        for title, p in title_to_path.items():
            if p == path:
                declaring_title = title
                break

        # conflicts_text에 언급된 각 상대방이 역방향으로도 선언했는지 확인
        for other_title, other_path in title_to_path.items():
            if other_path == path:
                continue
            if other_title not in conflicts_text and other_path not in conflicts_text:
                continue
            # 상대방이 역방향으로 선언했는지 확인
            other_conflicts = path_to_conflicts.get(other_path, "")
            if declaring_title and declaring_title not in other_conflicts and path not in other_conflicts:
                asymmetric.append(path)
                break

    _asymmetric_conflicts = asymmetric
    if asymmetric:
        logger.warning("Asymmetric conflicts_with declarations: %s", asymmetric)
