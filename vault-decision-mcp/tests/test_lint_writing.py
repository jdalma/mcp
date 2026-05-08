"""Tests for lint writing_hygiene rules."""

from __future__ import annotations

from pathlib import Path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


NO_RATIONALE = """\
---
type: decision
status: decided
created: "2024-01-01"
tags: [architecture]
---

# Decision: No Rationale

## Decision

Option A를 선택했다.
"""

NO_CREATED = """\
---
type: decision
status: decided
tags: [architecture]
---

# Decision: No Created Date

## Decision

Option B를 선택했다.

## Rationale

이유가 있다.
"""

NO_TAGS = """\
---
type: decision
status: decided
created: "2024-01-01"
---

# Decision: No Tags

## Decision

Option C를 선택했다.

## Rationale

이유가 있다.
"""

DANGLING_CANDIDATE = """\
---
type: note
status: draft
created: "2024-01-01"
tags: [architecture]
decision_candidates:
  - "Option A"
  - "Option B"
---

# Note: Pending Decision

아직 결정 못했다.
"""


def test_lint_missing_rationale(tmp_path, monkeypatch):
    """## Rationale 섹션 없는 decision이 missing_rationale로 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - No Rationale.md", NO_RATIONALE)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_missing_rationale(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "missing_rationale"]
    assert rule_issues, "## Rationale 없는 결정이 missing_rationale로 보고되지 않음"
    assert any("No Rationale" in i["path"] or "No Rationale" in i["message"]
               for i in rule_issues)


def test_lint_missing_created_date(tmp_path, monkeypatch):
    """frontmatter created 필드 없는 decision이 missing_created로 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - No Created Date.md", NO_CREATED)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_missing_created(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "missing_created"]
    assert rule_issues, "created 필드 없는 결정이 missing_created로 보고되지 않음"


def test_lint_missing_tags(tmp_path, monkeypatch):
    """frontmatter tags 없는 decision이 missing_tags로 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - No Tags.md", NO_TAGS)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_missing_tags(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "missing_tags"]
    assert rule_issues, "tags 없는 결정이 missing_tags로 보고되지 않음"


def test_lint_dangling_candidate(tmp_path, monkeypatch):
    """decision_candidates 있고 status가 draft인 노트가 dangling_candidate로 보고된다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Note - Pending Decision.md", DANGLING_CANDIDATE)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    issues = lint.check_dangling_candidate(tmp_path)
    rule_issues = [i for i in issues if i["rule"] == "dangling_candidate"]
    assert rule_issues, "decision_candidates 있는 draft 노트가 dangling_candidate로 보고되지 않음"


def test_lint_writing_hygiene_scope(tmp_path, monkeypatch):
    """run_lint(scope='writing_hygiene')가 writing_hygiene 룰만 실행한다."""
    import lint
    import config

    notes = tmp_path / "01 Notes"
    _write(notes / "Decision - No Rationale.md", NO_RATIONALE)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    result = lint.run_lint(tmp_path, scope="writing_hygiene")
    rules_found = {i["rule"] for i in result["issues"]}

    # writing_hygiene 룰이 포함돼야 함
    writing_hygiene_rules = {"missing_rationale", "missing_created", "missing_tags", "dangling_candidate"}
    assert rules_found & writing_hygiene_rules, (
        f"writing_hygiene scope에서 writing_hygiene 룰이 없음: {rules_found}"
    )
