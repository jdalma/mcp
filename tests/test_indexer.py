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
        notes_dir = Path(tmpdir) / "01 Notes"
        notes_dir.mkdir()
        (notes_dir / "Decision - Test.md").write_text(SAMPLE_DECISION)
        (notes_dir / "Regular Note.md").write_text(SAMPLE_NOTE)
        maps_dir = Path(tmpdir) / "02 Maps"
        maps_dir.mkdir()
        (maps_dir / "MOC - Test.md").write_text("# MOC\n\nlinks")

        files = collect_vault_files(Path(tmpdir))
        assert len(files) == 3
        names = [f.name for f in files]
        assert "Decision - Test.md" in names
        assert "Regular Note.md" in names
        assert "MOC - Test.md" in names


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
