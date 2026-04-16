"""Tests for indexer module — vault file parsing and document preparation."""

import tempfile
from pathlib import Path

SAMPLE_DECISION = """---
type: decision
status: decided
created: "2026-04-12"
updated: "2026-04-12"
tags: [decision, test]
sources: ["self"]
mocs: ["[[MOC - Engineering]]"]
---

# Decision: 테스트 결정

## Context

테스트용 결정 문서.

## Decision

Option A를 선택한다.

## Rationale

Option B보다 단순하다.
"""

SAMPLE_NOTE = """---
type: note
status: confirmed
created: "2026-04-10"
tags: [architecture]
sources: ["self"]
mocs: []
decision_candidates: []
---

# 아키텍처 설계 원칙

컴포넌트는 단일 책임을 가진다.
"""


def test_parse_frontmatter_and_body():
    from indexer import parse_markdown

    meta, body = parse_markdown(SAMPLE_DECISION)
    assert meta["type"] == "decision"
    assert meta["status"] == "decided"
    assert "Option A를 선택한다" in body


def test_parse_no_frontmatter():
    from indexer import parse_markdown

    meta, body = parse_markdown("# Just a title\n\nSome content.")
    assert meta == {}
    assert "Just a title" in body


def test_collect_vault_files():
    from indexer import collect_vault_files

    with tempfile.TemporaryDirectory() as tmpdir:
        inbox_dir = Path(tmpdir) / "00 Inbox"
        inbox_dir.mkdir()
        (inbox_dir / "Payment MSA.md").write_text("# Payment MSA\n\ncontent")

        notes_dir = Path(tmpdir) / "01 Notes"
        notes_dir.mkdir()
        (notes_dir / "Decision - Test.md").write_text(SAMPLE_DECISION)
        (notes_dir / "Regular Note.md").write_text(SAMPLE_NOTE)

        maps_dir = Path(tmpdir) / "02 Maps"
        maps_dir.mkdir()
        (maps_dir / "MOC - Test.md").write_text("# MOC\n\nlinks")

        sources_dir = Path(tmpdir) / "03 Sources"
        sources_dir.mkdir()
        (sources_dir / "Reference A.md").write_text("# Ref\n\nsource")

        archive_dir = Path(tmpdir) / "99 Archive" / "2026"
        archive_dir.mkdir(parents=True)
        (archive_dir / "Old Analysis.md").write_text("# Old\n\narchived")

        # templates/ should NOT be indexed
        templates_dir = Path(tmpdir) / "templates"
        templates_dir.mkdir()
        (templates_dir / "Template.md").write_text("# Template\n\nskip")

        files = collect_vault_files(Path(tmpdir))
        assert len(files) == 6
        names = [f.name for f in files]
        assert "Payment MSA.md" in names
        assert "Decision - Test.md" in names
        assert "Regular Note.md" in names
        assert "MOC - Test.md" in names
        assert "Reference A.md" in names
        assert "Old Analysis.md" in names
        assert "Template.md" not in names


def test_prepare_documents():
    from indexer import parse_markdown, prepare_document

    meta, body = parse_markdown(SAMPLE_DECISION)
    doc = prepare_document(
        file_path=Path("/vault/01 Notes/Decision - Test.md"),
        metadata=meta,
        body=body,
        vault_path=Path("/vault"),
    )
    assert doc["id"] == "01 Notes/Decision - Test.md"
    assert doc["metadata"]["type"] == "decision"
    assert "Option A를 선택한다" in doc["document"]


def test_incremental_index():
    """변경되지 않은 파일은 재인덱싱하지 않는 증분 인덱싱 테스트."""
    import time

    import chromadb

    from indexer import build_index

    client = chromadb.Client()
    collection = client.create_collection("test_incremental")

    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir)
        notes = vault / "01 Notes"
        notes.mkdir()
        (notes / "Decision - A.md").write_text(SAMPLE_DECISION)

        # 첫 인덱싱 (force)
        count1 = build_index(collection, vault_path=vault, force=True)
        assert count1 == 1

        # 변경 없이 증분 인덱싱 — 카운트 동일
        count2 = build_index(collection, vault_path=vault, force=False)
        assert count2 == 1

        # 파일 추가 후 증분 인덱싱
        time.sleep(0.05)  # mtime 차이 보장
        (notes / "Note B.md").write_text(SAMPLE_NOTE)
        count3 = build_index(collection, vault_path=vault, force=False)
        assert count3 == 2


def test_incremental_index_deletes_removed_files():
    """삭제된 파일이 인덱스에서 제거되는지 테스트."""
    import chromadb

    from indexer import build_index

    client = chromadb.Client()
    collection = client.create_collection("test_incremental_delete")

    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir)
        notes = vault / "01 Notes"
        notes.mkdir()
        file_a = notes / "Decision - A.md"
        file_b = notes / "Note B.md"
        file_a.write_text(SAMPLE_DECISION)
        file_b.write_text(SAMPLE_NOTE)

        # 전체 인덱싱
        count1 = build_index(collection, vault_path=vault, force=True)
        assert count1 == 2

        # 파일 하나 삭제 후 증분 인덱싱
        file_b.unlink()
        count2 = build_index(collection, vault_path=vault, force=False)
        assert count2 == 1
