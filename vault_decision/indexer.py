"""Vault → SQLite (FTS5 + bge-m3 embedding) indexer."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from vault_decision.config import (
    INDEX_PATTERNS,
    get_embedding_model,
    get_index_path,
    get_vault_path,
)

logger = logging.getLogger(__name__)

_embedder = None


# bge-m3는 max_seq=8192를 지원하지만 attention 메모리는 시퀀스 길이의 제곱.
# 의사결정 노트의 핵심은 앞부분(제목+context+Decision/Rationale)이므로 1024로 충분하고
# 메모리도 안전하다 (batch=1 기준 ~150MB).
EMBED_MAX_SEQ_LENGTH = 1024


def get_embedder(model_name: str | None = None):
    """Lazily load the SentenceTransformer model. Module-global cache."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        name = model_name or get_embedding_model()
        logger.info("Loading embedding model: %s", name)
        model = SentenceTransformer(name)
        model.max_seq_length = EMBED_MAX_SEQ_LENGTH
        _embedder = model
    return _embedder


def parse_markdown(text: str, source: str | None = None) -> tuple[dict, str]:
    """YAML frontmatter와 body를 분리한다. 파싱 실패 시 빈 dict + warning."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        logger.warning("YAML parse failed%s: %s", f" for {source}" if source else "", e)
        meta = {}
    if not isinstance(meta, dict):
        logger.warning("YAML frontmatter is not a mapping%s", f" for {source}" if source else "")
        meta = {}
    return meta, parts[2].strip()


def infer_path_role(relative_path: str, metadata: dict) -> str:
    """Path/frontmatter에서 vault 역할을 추론."""
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
    return "unknown"


def collect_vault_files(vault: Path) -> list[Path]:
    """INDEX_PATTERNS에 매칭되는 .md 파일을 수집. vault root 밖 symlink는 제외."""
    vault_root = vault.resolve()
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in INDEX_PATTERNS:
        for f in sorted(vault.glob(pattern)):
            if f in seen:
                continue
            try:
                f.resolve(strict=False).relative_to(vault_root)
            except ValueError:
                logger.warning("Skipping symlink that escapes vault: %s", f)
                continue
            seen.add(f)
            out.append(f)
    return out


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS docs (
  rowid INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  type TEXT,
  status TEXT,
  decision_status TEXT,
  human_reviewed INTEGER,
  decided_on TEXT,
  revisit_when TEXT,
  superseded_by TEXT,
  conflicts_with TEXT,
  context TEXT,
  body TEXT NOT NULL,
  mtime REAL NOT NULL,
  embedding BLOB,
  path_role TEXT,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_docs_path ON docs(path);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
  title, context, body,
  content='docs', content_rowid='rowid',
  tokenize="unicode61 remove_diacritics 2"
);

CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
  INSERT INTO docs_fts(rowid, title, context, body)
  VALUES (new.rowid, new.title, COALESCE(new.context, ''), new.body);
END;

CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, title, context, body)
  VALUES ('delete', old.rowid, old.title, COALESCE(old.context, ''), old.body);
END;

CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, title, context, body)
  VALUES ('delete', old.rowid, old.title, COALESCE(old.context, ''), old.body);
  INSERT INTO docs_fts(rowid, title, context, body)
  VALUES (new.rowid, new.title, COALESCE(new.context, ''), new.body);
END;
"""


def open_index(index_path: Path) -> sqlite3.Connection:
    """SQLite connection을 연다. 부모 디렉터리 자동 생성."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_path)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def _to_bool_int(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"true", "yes", "1"} else 0
    return 1 if value else 0


def _str_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _build_embed_text(title: str, context: str, body: str) -> str:
    head = f"# {title}"
    if context:
        head += f"\n{context}"
    return f"{head}\n\n{body}"


def build_index(
    conn: sqlite3.Connection,
    vault: Path,
    *,
    model_name: str | None = None,
    force: bool = False,
) -> int:
    """Vault → docs 테이블 인덱싱. 임베딩 실패 시 부분 commit 없음."""
    ensure_schema(conn)
    files = collect_vault_files(vault)

    if force:
        with conn:
            conn.execute("DELETE FROM docs")

    existing: dict[str, float] = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, mtime FROM docs").fetchall()
    }

    current_paths: set[str] = set()
    pending: list[tuple] = []
    embed_batch_texts: list[str] = []
    embed_batch_indices: list[int] = []

    for f in files:
        rel = str(f.relative_to(vault))
        current_paths.add(rel)
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if not force and existing.get(rel) == mtime:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to read %s: %s", f, e)
            continue

        meta, body = parse_markdown(text, source=rel)
        title = f.stem
        context = _str_or_empty(meta.get("context"))
        path_role = infer_path_role(rel, meta)

        record = {
            "path": rel,
            "title": title,
            "type": meta.get("type") or "unknown",
            "status": _str_or_empty(meta.get("status")) or None,
            "decision_status": _str_or_empty(meta.get("decision_status")) or None,
            "human_reviewed": _to_bool_int(meta.get("human_reviewed")),
            "decided_on": _str_or_empty(meta.get("decided_on")) or None,
            "revisit_when": _str_or_empty(meta.get("revisit_when")) or None,
            "superseded_by": _str_or_empty(meta.get("superseded_by")) or None,
            "conflicts_with": _str_or_empty(meta.get("conflicts_with")) or None,
            "context": context or None,
            "body": body,
            "mtime": mtime,
            "path_role": path_role,
            "metadata_json": json.dumps(meta, ensure_ascii=False, sort_keys=True, default=str),
        }
        pending.append(record)
        embed_batch_indices.append(len(pending) - 1)
        embed_batch_texts.append(_build_embed_text(title, context, body))

    deleted = [p for p in existing.keys() if p not in current_paths]

    if not pending and not deleted and not force:
        logger.info("Index up-to-date. No changes.")
        return conn.execute("SELECT count(*) FROM docs").fetchone()[0]

    embeddings: list[bytes] = []
    if embed_batch_texts:
        model = get_embedder(model_name)
        # max_seq=1024로 제한해도 attention은 [seq^2]. batch>1이면 메모리 누적.
        # 본 vault 규모(<300노트)에선 batch=1로도 1~2분 안에 끝남.
        vectors = model.encode(embed_batch_texts, batch_size=1, show_progress_bar=False)
        vectors = np.asarray(vectors, dtype=np.float32)
        # L2 정규화 (코사인 유사도를 단순 dot product로 계산할 수 있도록)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms
        embeddings = [v.tobytes() for v in vectors]

    with conn:
        if deleted:
            conn.executemany("DELETE FROM docs WHERE path = ?", [(p,) for p in deleted])

        for i, rec in enumerate(pending):
            emb = embeddings[i] if i < len(embeddings) else None
            conn.execute(
                """
                INSERT INTO docs (
                  path, title, type, status, decision_status, human_reviewed,
                  decided_on, revisit_when, superseded_by, conflicts_with,
                  context, body, mtime, embedding, path_role, metadata_json
                ) VALUES (
                  :path, :title, :type, :status, :decision_status, :human_reviewed,
                  :decided_on, :revisit_when, :superseded_by, :conflicts_with,
                  :context, :body, :mtime, :embedding, :path_role, :metadata_json
                )
                ON CONFLICT(path) DO UPDATE SET
                  title=excluded.title, type=excluded.type, status=excluded.status,
                  decision_status=excluded.decision_status,
                  human_reviewed=excluded.human_reviewed,
                  decided_on=excluded.decided_on, revisit_when=excluded.revisit_when,
                  superseded_by=excluded.superseded_by,
                  conflicts_with=excluded.conflicts_with,
                  context=excluded.context, body=excluded.body, mtime=excluded.mtime,
                  embedding=excluded.embedding, path_role=excluded.path_role,
                  metadata_json=excluded.metadata_json
                """,
                {**rec, "embedding": emb},
            )

    total = conn.execute("SELECT count(*) FROM docs").fetchone()[0]
    logger.info(
        "Indexed %d documents (%d updated, %d deleted).",
        total, len(pending), len(deleted),
    )
    return total


def stats(conn: sqlite3.Connection) -> dict:
    ensure_schema(conn)
    total = conn.execute("SELECT count(*) FROM docs").fetchone()[0]
    by_type = dict(
        conn.execute("SELECT type, count(*) FROM docs GROUP BY type").fetchall()
    )
    by_status = dict(
        conn.execute("SELECT status, count(*) FROM docs GROUP BY status").fetchall()
    )
    by_role = dict(
        conn.execute("SELECT path_role, count(*) FROM docs GROUP BY path_role").fetchall()
    )
    return {"total": total, "by_type": by_type, "by_status": by_status, "by_role": by_role}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(prog="vault_decision.indexer")
    parser.add_argument("command", choices=["build", "stats"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    conn = open_index(get_index_path())
    try:
        if args.command == "build":
            count = build_index(conn, get_vault_path(), force=args.force)
            print(f"Indexed {count} documents.")
        elif args.command == "stats":
            print(json.dumps(stats(conn), ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
