"""scripts/migrate_canonical.py sanity test.

vault 데이터 무결성을 위해 텍스트 패치 동작을 케이스별 검증.
Phase 4 P4-0 게이트.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_canonical import (  # noqa: E402
    classify_canonical,
    patch_canonical,
    read_frontmatter_meta,
)


# --- patch_canonical: 원본 보존 검증 ---


def test_no_frontmatter_prepends_new_block():
    text = "# Title\n\nbody"
    out, changed = patch_canonical(text, True)
    assert changed
    assert out.startswith("---\ncanonical: true\n---\n")
    assert "# Title" in out


def test_existing_frontmatter_appends_canonical():
    text = "---\ntype: decision\nstatus: decided\n---\n\n# Body\n"
    out, changed = patch_canonical(text, True)
    assert changed
    assert "canonical: true" in out
    assert "type: decision" in out
    assert "status: decided" in out
    assert "# Body" in out


def test_existing_canonical_same_value_noop():
    text = "---\ntype: decision\ncanonical: true\n---\nbody\n"
    out, changed = patch_canonical(text, True)
    assert not changed
    assert out == text


def test_existing_canonical_different_value_replaces():
    text = "---\ntype: decision\ncanonical: false\n---\nbody\n"
    out, changed = patch_canonical(text, True)
    assert changed
    assert "canonical: true" in out
    assert "canonical: false" not in out


def test_preserves_yaml_comments():
    text = "---\ntype: decision    # important\nstatus: decided  # ratified\n---\nbody\n"
    out, _ = patch_canonical(text, True)
    assert "# important" in out
    assert "# ratified" in out


def test_preserves_quote_styles():
    text = '---\ncontext: "quoted value"\nlist: [\'a\', \'b\']\n---\nbody\n'
    out, _ = patch_canonical(text, True)
    assert '"quoted value"' in out
    assert "['a', 'b']" in out


def test_preserves_key_order():
    text = "---\nz: 1\na: 2\nm: 3\n---\nbody\n"
    out, _ = patch_canonical(text, True)
    z = out.index("z: 1")
    a = out.index("a: 2")
    m = out.index("m: 3")
    c = out.index("canonical: true")
    assert z < a < m < c


def test_preserves_body_after_frontmatter():
    text = "---\ntype: decision\n---\n\n# Decision body\n\nLong content here.\n"
    out, _ = patch_canonical(text, True)
    assert "# Decision body" in out
    assert "Long content here." in out


def test_canonical_false_value():
    text = "---\ntype: note\n---\nbody"
    out, _ = patch_canonical(text, False)
    assert "canonical: false" in out


# --- read_frontmatter_meta: 파싱 실패 처리 ---


def test_unclosed_frontmatter_returns_parse_failure():
    text = "---\ntype: decision\n(no closing dashes)\nbody"
    meta, ok = read_frontmatter_meta(text)
    assert not ok
    assert meta is None


def test_malformed_yaml_returns_parse_failure():
    text = "---\ntype: [unclosed list\n---\nbody"
    meta, ok = read_frontmatter_meta(text)
    assert not ok


def test_empty_frontmatter_returns_empty_dict():
    text = "---\n---\nbody"
    meta, ok = read_frontmatter_meta(text)
    assert ok
    assert meta == {}


def test_no_frontmatter_returns_empty_dict():
    text = "# Title\n\nbody"
    meta, ok = read_frontmatter_meta(text)
    assert ok
    assert meta == {}


def test_valid_frontmatter_returns_dict():
    text = "---\ntype: decision\nstatus: decided\n---\nbody"
    meta, ok = read_frontmatter_meta(text)
    assert ok
    assert meta == {"type": "decision", "status": "decided"}


# --- classify_canonical: 분류 룰 검증 ---


def test_classify_decision_with_decided_status_true():
    assert classify_canonical(
        "01 Notes/Decision - X.md", {"status": "decided"}
    ) is True


def test_classify_decision_with_draft_status_false():
    assert classify_canonical(
        "01 Notes/Decision - X.md", {"status": "draft"}
    ) is False


def test_classify_decision_without_status_false():
    assert classify_canonical("01 Notes/Decision - X.md", {}) is False


def test_classify_note_outside_decision_prefix_false():
    assert classify_canonical(
        "01 Notes/SomeNote.md", {"status": "decided"}
    ) is False


def test_classify_source_dir_false():
    assert classify_canonical(
        "03 Sources/External.md", {"status": "decided"}
    ) is False


def test_classify_moc_dir_false():
    assert classify_canonical("02 Maps/Index.md", {}) is False
