"""Phase 3 P3-1: lint 3룰 단위 테스트.

in-memory SQLite + ensure_schema + 수동 INSERT. 실 vault 의존 X.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from vault_decision.indexer import ensure_schema
from vault_decision.lint import (
    _attach_metadata,
    _build_summary,
    _fetch_reviewable_decisions,
    find_asymmetric_conflicts,
    find_stale_decisions,
    find_superseded_dangling,
    lint,
)

TODAY = date(2026, 5, 17)


def _insert(
    conn: sqlite3.Connection,
    *,
    path: str,
    title: str,
    type: str = "decision",
    status: str | None = "decided",
    decision_status: str | None = None,
    human_reviewed: int = 1,
    revisit_when: str | None = None,
    conflicts_with: str | None = None,
    body: str = "",
    metadata: dict | None = None,
) -> None:
    meta = metadata if metadata is not None else {}
    if conflicts_with and "conflicts_with" not in meta:
        meta["conflicts_with"] = conflicts_with
    if revisit_when and "revisit_when" not in meta:
        meta["revisit_when"] = revisit_when
    conn.execute(
        """
        INSERT INTO docs (
          path, title, type, status, decision_status, human_reviewed,
          decided_on, revisit_when, superseded_by, conflicts_with,
          context, body, mtime, embedding, path_role, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, NULL, ?, 0, NULL, 'active_decision', ?)
        """,
        (
            path,
            title,
            type,
            status,
            decision_status,
            human_reviewed,
            revisit_when,
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
    rows = _fetch_reviewable_decisions(conn)
    assert rows == []


def test_fetch_excludes_archive(conn):
    _insert(conn, path="99 Archive/Old.md", title="Old")
    rows = _fetch_reviewable_decisions(conn)
    assert rows == []


def test_fetch_excludes_unreviewed(conn):
    _insert(conn, path="01 Notes/Decision - X.md", title="X", human_reviewed=0)
    rows = _fetch_reviewable_decisions(conn)
    assert rows == []


def test_fetch_excludes_note_type(conn):
    _insert(conn, path="01 Notes/N.md", title="N", type="note")
    rows = _fetch_reviewable_decisions(conn)
    assert rows == []


def test_fetch_includes_reviewable_decision(conn):
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
    # 강제로 metadata_json을 corrupt 값으로 덮어쓰기
    conn.execute("UPDATE docs SET metadata_json = ? WHERE path = ?", ("not-json", "01 Notes/Decision - X.md"))
    rows = _fetch_reviewable_decisions(conn)
    out = _attach_metadata(rows)
    assert out[0]["metadata"] == {}


# --- 룰 1: asymmetric_conflict ---


def _make(rows: list[dict]) -> list[dict]:
    """헬퍼: dict 리스트의 metadata 필드를 안전 형태로 보강."""
    for r in rows:
        r.setdefault("metadata", {})
        r.setdefault("decision_status", None)
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
    issues = find_asymmetric_conflicts(rows)
    assert issues == []


def test_asymmetric_conflict_target_not_indexed():
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A", "metadata": {"conflicts_with": ["NonExistent"]}},
    ])
    assert find_asymmetric_conflicts(rows) == []


def test_asymmetric_conflict_superseded_excluded_from_active():
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A",
         "decision_status": "superseded",
         "metadata": {"conflicts_with": ["B"]}},
        {"path": "01 Notes/Decision - B.md", "title": "B", "metadata": {"conflicts_with": []}},
    ])
    issues = find_asymmetric_conflicts(rows)
    assert issues == []


def test_asymmetric_conflict_missing_conflicts_with_key_safe():
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A", "metadata": {}},
    ])
    assert find_asymmetric_conflicts(rows) == []  # KeyError 없이 통과


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
    # B가 2개 있는데 그 중 1개만 A를 reciprocate → A의 단방향 issue 없음
    rows = _make([
        {"path": "01 Notes/Decision - A.md", "title": "A", "metadata": {"conflicts_with": ["B"]}},
        {"path": "01 Notes/Decision - B (1).md", "title": "B", "metadata": {"conflicts_with": ["A"]}},
        {"path": "01 Notes/Decision - B (2).md", "title": "B", "metadata": {"conflicts_with": []}},
    ])
    issues = find_asymmetric_conflicts(rows)
    # B title collision은 2개 (B 본인들) — A의 단방향 issue는 없음
    assert all(i["rule"] == "asymmetric_conflict" for i in issues)
    a_issues = [i for i in issues if i["title"] == "A"]
    assert a_issues == []
    b_collision_issues = [i for i in issues if i["title"] == "B" and "collision" in i["detail"]]
    assert len(b_collision_issues) == 2


# --- 룰 2: stale_decision ---


def test_stale_decision_past_revisit():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "status": "decided", "decision_status": None, "revisit_when": "2020-01-01"},
    ])
    issues = find_stale_decisions(rows, TODAY)
    assert len(issues) == 1
    assert "is in the past" in issues[0]["detail"]


def test_stale_decision_future_revisit():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "status": "decided", "decision_status": None, "revisit_when": "2099-01-01"},
    ])
    assert find_stale_decisions(rows, TODAY) == []


def test_stale_decision_no_revisit():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "status": "decided", "decision_status": None, "revisit_when": None},
    ])
    assert find_stale_decisions(rows, TODAY) == []


def test_stale_decision_invalid_date_string():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "status": "decided", "decision_status": None, "revisit_when": "not-a-date"},
    ])
    assert find_stale_decisions(rows, TODAY) == []


def test_stale_decision_draft_status_guarded_out():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "status": "draft", "decision_status": None, "revisit_when": "2020-01-01"},
    ])
    assert find_stale_decisions(rows, TODAY) == []


def test_stale_decision_superseded_guarded_out():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "status": "decided", "decision_status": "superseded", "revisit_when": "2020-01-01"},
    ])
    assert find_stale_decisions(rows, TODAY) == []


# --- 룰 3: superseded_dangling ---


def test_superseded_dangling_h2_heading_with_null_status():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "decision_status": None,
         "body": "Some intro.\n\n## Superseded by [[Y]]\n\nReason..."},
    ])
    issues = find_superseded_dangling(rows)
    assert len(issues) == 1
    assert "Superseded by" in issues[0]["detail"]


def test_superseded_dangling_h2_heading_with_superseded_status_ok():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "decision_status": "superseded",
         "body": "## Superseded by [[Y]]"},
    ])
    assert find_superseded_dangling(rows) == []


def test_superseded_dangling_h3_heading_ignored():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "decision_status": None,
         "body": "### Superseded by [[Y]]"},
    ])
    assert find_superseded_dangling(rows) == []


def test_superseded_dangling_empty_body():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "decision_status": None,
         "body": ""},
    ])
    assert find_superseded_dangling(rows) == []


def test_superseded_dangling_case_insensitive_heading():
    rows = _make([
        {"path": "01 Notes/Decision - X.md", "title": "X",
         "decision_status": None,
         "body": "## superseded BY [[Y]]"},
    ])
    assert len(find_superseded_dangling(rows)) == 1


# --- _build_summary ---


def test_build_summary_zero():
    assert _build_summary([]) == "0 issues found"


def test_build_summary_mixed():
    issues = [
        {"rule": "asymmetric_conflict"},
        {"rule": "stale_decision"},
        {"rule": "stale_decision"},
    ]
    s = _build_summary(issues)
    assert s.startswith("3 issues found")
    assert "1 asymmetric_conflict" in s
    assert "2 stale_decision" in s


# --- 통합 lint() ---


def test_lint_integration_no_issues(conn):
    _insert(
        conn,
        path="01 Notes/Decision - Clean.md",
        title="Clean",
        status="decided",
        revisit_when="2099-01-01",
        body="Clean body.",
    )
    result = lint(conn, today=TODAY)
    assert result["issues"] == []
    assert result["summary"] == "0 issues found"


def test_lint_integration_all_rules_fire(conn):
    # 1) asymmetric: A→B 단방향
    _insert(
        conn, path="01 Notes/Decision - A.md", title="A",
        conflicts_with="B", metadata={"conflicts_with": ["B"]},
    )
    _insert(conn, path="01 Notes/Decision - B.md", title="B")

    # 2) stale: 만료
    _insert(
        conn, path="01 Notes/Decision - Old.md", title="Old",
        revisit_when="2020-01-01",
        metadata={"revisit_when": "2020-01-01"},
    )

    # 3) superseded_dangling: 본문 헤딩 있는데 frontmatter superseded 아님
    _insert(
        conn, path="01 Notes/Decision - Dangling.md", title="Dangling",
        body="\n## Superseded by [[NewOne]]\n",
    )

    # noise: 00 Inbox/ 노트는 모든 룰에서 제외
    _insert(
        conn, path="00 Inbox/Junk.md", title="Junk",
        revisit_when="2020-01-01",
        body="## Superseded by",
        conflicts_with="A",
        metadata={"conflicts_with": ["A"], "revisit_when": "2020-01-01"},
    )

    result = lint(conn, today=TODAY)
    rules = sorted(i["rule"] for i in result["issues"])
    assert rules == ["asymmetric_conflict", "stale_decision", "superseded_dangling"]
    # 00 Inbox/Junk.md는 어떤 issue에도 없음
    assert all("00 Inbox/" not in i["path"] for i in result["issues"])


def test_lint_today_defaults_to_today(conn):
    """today 인자 생략 시 date.today() 사용 확인 (스모크)."""
    _insert(
        conn,
        path="01 Notes/Decision - X.md",
        title="X",
        revisit_when="2099-01-01",  # 미래 → stale 아님
        metadata={"revisit_when": "2099-01-01"},
    )
    result = lint(conn)  # today 인자 없음
    assert result["issues"] == []
