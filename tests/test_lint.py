"""Phase 3.5 P35-2: lint 단위 테스트 (asymmetric_conflict 1룰만).

in-memory SQLite + ensure_schema + 수동 INSERT. 실 vault 의존 X.
stale_decision / superseded_dangling 룰은 Phase 3.5에서 폐기됨.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from vault_decision.indexer import ensure_schema
from vault_decision.lint import (
    _attach_metadata,
    _build_summary,
    _fetch_reviewable_decisions,
    find_asymmetric_conflicts,
    lint,
)


def _insert(
    conn: sqlite3.Connection,
    *,
    path: str,
    title: str,
    type: str = "decision",
    canonical: int = 1,
    conflicts_with: str | None = None,
    body: str = "",
    metadata: dict | None = None,
) -> None:
    meta = metadata if metadata is not None else {}
    if conflicts_with and "conflicts_with" not in meta:
        meta["conflicts_with"] = conflicts_with
    conn.execute(
        """
        INSERT INTO docs (
          path, title, type, canonical, conflicts_with,
          context, body, mtime, embedding, path_role, metadata_json
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, 0, NULL, 'active_decision', ?)
        """,
        (
            path,
            title,
            type,
            canonical,
            conflicts_with,
            body,
            json.dumps(meta, ensure_ascii=False, sort_keys=True),
        ),
    )


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


# --- _fetch_reviewable_decisions 공통 필터 ---


def test_fetch_excludes_inbox(conn):
    _insert(conn, path="00 Inbox/Draft.md", title="Draft")
    assert _fetch_reviewable_decisions(conn) == []


def test_fetch_excludes_archive(conn):
    _insert(conn, path="99 Archive/Old.md", title="Old")
    assert _fetch_reviewable_decisions(conn) == []


def test_fetch_excludes_non_canonical(conn):
    _insert(conn, path="01 Notes/Decision - X.md", title="X", canonical=0)
    assert _fetch_reviewable_decisions(conn) == []


def test_fetch_excludes_note_type(conn):
    _insert(conn, path="01 Notes/N.md", title="N", type="note")
    assert _fetch_reviewable_decisions(conn) == []


def test_fetch_includes_canonical_decision(conn):
    _insert(conn, path="01 Notes/Decision - X.md", title="X")
    rows = _fetch_reviewable_decisions(conn)
    assert len(rows) == 1


# --- _attach_metadata ---


def test_attach_metadata_parses_json(conn):
    _insert(
        conn,
        path="01 Notes/Decision - X.md",
        title="X",
        metadata={"foo": "bar", "conflicts_with": ["Y"]},
    )
    rows = _fetch_reviewable_decisions(conn)
    out = _attach_metadata(rows)
    assert out[0]["metadata"] == {"foo": "bar", "conflicts_with": ["Y"]}


def test_attach_metadata_fallback_on_invalid_json(conn):
    _insert(conn, path="01 Notes/Decision - X.md", title="X")
    conn.execute("UPDATE docs SET metadata_json = ? WHERE path = ?", ("not-json", "01 Notes/Decision - X.md"))
    rows = _fetch_reviewable_decisions(conn)
    out = _attach_metadata(rows)
    assert out[0]["metadata"] == {}


# --- 룰 1: asymmetric_conflict (Phase 3.5 — 유일한 룰) ---


def _make(rows: list[dict]) -> list[dict]:
    for r in rows:
        r.setdefault("metadata", {})
    return rows


def test_asymmetric_conflict_unilateral():
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A", "metadata": {"conflicts_with": ["B"]}},
        {"path": "01 Notes/Decision - B.md", "title": "B", "metadata": {"conflicts_with": []}},
    ])
    issues = find_asymmetric_conflicts(rows)
    assert len(issues) == 1
    assert issues[0]["title"] == "A"
    assert "does not reciprocate" in issues[0]["detail"]


def test_asymmetric_conflict_bilateral_yields_no_issue():
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A", "metadata": {"conflicts_with": ["B"]}},
        {"path": "01 Notes/Decision - B.md", "title": "B", "metadata": {"conflicts_with": ["A"]}},
    ])
    assert find_asymmetric_conflicts(rows) == []


def test_asymmetric_conflict_target_not_indexed():
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A", "metadata": {"conflicts_with": ["NonExistent"]}},
    ])
    assert find_asymmetric_conflicts(rows) == []


def test_asymmetric_conflict_missing_conflicts_with_key_safe():
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A", "metadata": {}},
    ])
    assert find_asymmetric_conflicts(rows) == []


def test_asymmetric_conflict_title_collision():
    rows = _make([
        {"path": "01 Notes/Decision - A (1).md", "title": "A", "metadata": {}},
        {"path": "01 Notes/Decision - A (2).md", "title": "A", "metadata": {}},
    ])
    issues = find_asymmetric_conflicts(rows)
    assert len(issues) == 2
    assert all("title collision" in i["detail"] for i in issues)
    assert all("2 notes share title 'A'" in i["detail"] for i in issues)


def test_asymmetric_conflict_partial_reciprocation_among_collision():
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A", "metadata": {"conflicts_with": ["B"]}},
        {"path": "01 Notes/Decision - B (1).md", "title": "B", "metadata": {"conflicts_with": ["A"]}},
        {"path": "01 Notes/Decision - B (2).md", "title": "B", "metadata": {"conflicts_with": []}},
    ])
    issues = find_asymmetric_conflicts(rows)
    a_issues = [i for i in issues if i["title"] == "A"]
    assert a_issues == []
    b_collision_issues = [i for i in issues if i["title"] == "B" and "collision" in i["detail"]]
    assert len(b_collision_issues) == 2


# --- _build_summary ---


def test_build_summary_zero():
    assert _build_summary([]) == "0 issues found"


def test_build_summary_single_rule():
    issues = [
        {"rule": "asymmetric_conflict"},
        {"rule": "asymmetric_conflict"},
    ]
    s = _build_summary(issues)
    assert s == "2 issues found (2 asymmetric_conflict)"


# --- 통합 lint() ---


def test_lint_integration_no_issues(conn):
    _insert(
        conn,
        path="01 Notes/Decision - Clean.md",
        title="Clean",
        body="Clean body.",
    )
    result = lint(conn)
    assert result["issues"] == []
    assert result["summary"] == "0 issues found"


def test_lint_integration_only_asymmetric_rule(conn):
    # 단방향 conflict — 유일하게 잡혀야 할 케이스
    _insert(
        conn, path="01 Notes/Decision - A.md", title="A",
        conflicts_with="B", metadata={"conflicts_with": ["B"]},
    )
    _insert(conn, path="01 Notes/Decision - B.md", title="B")

    # noise: 00 Inbox는 제외 / canonical=0은 제외
    _insert(
        conn, path="00 Inbox/Junk.md", title="Junk",
        conflicts_with="A", metadata={"conflicts_with": ["A"]},
    )
    _insert(
        conn, path="01 Notes/Decision - NonCanonical.md", title="NonCanonical",
        canonical=0, conflicts_with="A", metadata={"conflicts_with": ["A"]},
    )

    result = lint(conn)
    rules = {i["rule"] for i in result["issues"]}
    assert rules == {"asymmetric_conflict"}
    assert all("00 Inbox/" not in i["path"] for i in result["issues"])
    assert all("NonCanonical" not in i["title"] for i in result["issues"])


def test_lint_signature_has_no_today_argument():
    """lint() 시그니처에서 today 인자가 사라졌는지 확인 (Phase 3.5)."""
    from inspect import signature
    params = signature(lint).parameters
    assert "today" not in params
    assert list(params.keys()) == ["conn"]
