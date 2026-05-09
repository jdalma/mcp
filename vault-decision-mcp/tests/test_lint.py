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


