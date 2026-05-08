"""Tests for lint MCP tool — production_safety rules."""

from __future__ import annotations

from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


STALE_DECISION = """\
---
type: decision
status: decided
revisit_when: "2020-01-01"
---

# Decision: Old Auth Strategy

## Decision

Option A를 선택했다.
"""

ASYMMETRIC_A = """\
---
type: decision
status: decided
conflicts_with:
  - "01 Notes/Decision - B.md"
---

# Decision: A

## Decision

A를 선택했다.
"""

ASYMMETRIC_B = """\
---
type: decision
status: decided
---

# Decision: B

## Decision

B를 선택했다.
"""

SUPERSEDED_NO_STATUS = """\
---
type: decision
status: decided
---

# Decision: Legacy Thing

## Decision

예전 방식을 선택했다.

## Superseded by

[[Decision - New Thing]]
"""

INDEX_MD = """\
# Index

## Decisions

- [[Decision - A]]
"""


# ── tests ─────────────────────────────────────────────────────────────────────

def test_lint_stale_decision(tmp_path, monkeypatch):
    """revisit_when 날짜가 지난 결정은 stale_decision 이슈로 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - Old Auth Strategy.md", STALE_DECISION)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_stale_decision(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "stale_decision"]
    assert rule_issues, "revisit_when이 지난 결정이 stale_decision으로 보고되지 않음"
    assert any("Old Auth Strategy" in i["path"] or "Old Auth Strategy" in i["message"]
               for i in rule_issues)


def test_lint_asymmetric_conflict(tmp_path, monkeypatch):
    """A→B 선언됐지만 B→A 미선언인 경우 asymmetric_conflict 이슈로 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - A.md", ASYMMETRIC_A)
    _write(notes / "Decision - B.md", ASYMMETRIC_B)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_asymmetric_conflict(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "asymmetric_conflict"]
    assert rule_issues, "비대칭 conflicts_with가 asymmetric_conflict로 보고되지 않음"


def test_lint_index_drift(tmp_path, monkeypatch):
    """01 Notes/Decision - *.md 파일이 index.md의 Decisions 섹션에 누락되면 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - A.md", ASYMMETRIC_A)
    _write(notes / "Decision - B.md", ASYMMETRIC_B)  # B는 index에 없음
    _write(tmp_path / "index.md", INDEX_MD)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_index_drift(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "index_drift"]
    assert rule_issues, "index.md에 누락된 Decision이 index_drift로 보고되지 않음"
    assert any("Decision - B" in i["message"] or "Decision - B" in i["path"]
               for i in rule_issues)


def test_lint_superseded_dangling(tmp_path, monkeypatch):
    """본문에 ## Superseded by 헤딩이 있지만 frontmatter decision_status가 없으면 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - Legacy Thing.md", SUPERSEDED_NO_STATUS)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_superseded_dangling(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "superseded_dangling"]
    assert rule_issues, (
        "## Superseded by 있고 frontmatter decision_status 없는 결정이 보고되지 않음"
    )
    assert any("Legacy Thing" in i["path"] or "Legacy Thing" in i["message"]
               for i in rule_issues)


# ── P2.3 writing_hygiene additional rules ────────────────────────────────────

REVISIT_TIME_HINT = """\
---
type: decision
status: decided
revisit_when: "운영 2-4주 후 재검토"
---

# Decision: Time Hint Only

## Decision

Option A.
"""

ORPHANED_NOTE = """\
---
type: note
status: confirmed
---

# Note: Orphaned

아무 연결도 없는 노트.
"""

INBOX_OLD = """\
# Raw Input

미처리 자료.
"""

UNPROCESSED_CANDIDATE_OLD = """\
---
type: note
status: draft
decision_candidates:
  - "Option A"
  - "Option B"
---

# Note: Old Candidate

오래된 후보 노트.
"""


def test_lint_revisit_when_time_hint_without_date(tmp_path, monkeypatch):
    """자유텍스트 revisit_when에 날짜(20XX-XX-XX)가 없으면 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - Time Hint Only.md", REVISIT_TIME_HINT)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_revisit_when_time_hint(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "revisit_when_time_hint"]
    assert rule_issues, "시간 힌트만 있는 revisit_when이 보고되지 않음"


def test_lint_orphaned_note(tmp_path, monkeypatch):
    """type=note + status≠draft + mocs/sources 비어있으면 orphaned_note로 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Note - Orphaned.md", ORPHANED_NOTE)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_orphaned_note(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "orphaned_note"]
    assert rule_issues, "mocs/sources 없는 confirmed note가 orphaned_note로 보고되지 않음"


def test_lint_inbox_aging(tmp_path, monkeypatch):
    """00 Inbox/ 파일이 30일+ 경과하면 inbox_aging으로 보고된다."""
    import lint
    import config
    import os
    import time

    inbox = tmp_path / "00 Inbox"
    old_file = _write(inbox / "old_raw.md", INBOX_OLD)
    # mtime을 31일 전으로 변경
    old_mtime = time.time() - (31 * 24 * 3600)
    os.utime(str(old_file), (old_mtime, old_mtime))
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_inbox_aging(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "inbox_aging"]
    assert rule_issues, "30일+ Inbox 파일이 inbox_aging으로 보고되지 않음"


def test_lint_unprocessed_candidate(tmp_path, monkeypatch):
    """decision_candidates 있고 180일+ 미갱신 노트가 unprocessed_candidate로 보고된다."""
    import lint
    import config
    import os
    import time

    notes = tmp_path / "01 Notes"
    old_file = _write(notes / "Note - Old Candidate.md", UNPROCESSED_CANDIDATE_OLD)
    # mtime을 181일 전으로 변경
    old_mtime = time.time() - (181 * 24 * 3600)
    os.utime(str(old_file), (old_mtime, old_mtime))
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_unprocessed_candidate(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "unprocessed_candidate"]
    assert rule_issues, "180일+ 미갱신 decision_candidates 노트가 보고되지 않음"
