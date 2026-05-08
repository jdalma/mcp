"""Vault hygiene lint rules for the MCP lint tool."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from config import get_vault_path


def _issue(rule: str, severity: str, path: str, message: str) -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "path": path, "message": message}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, parts[2].strip()


def _decision_files(vault: Path) -> list[Path]:
    notes = vault / "01 Notes"
    if not notes.exists():
        return []
    return sorted(notes.glob("Decision - *.md"))


def check_stale_decision(vault: Path | None = None) -> list[dict]:
    """revisit_when 날짜가 오늘보다 과거인 결정을 보고한다."""
    vault = vault or get_vault_path()
    today = date.today()
    issues = []

    for f in _decision_files(vault):
        text = f.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(text)
        revisit = meta.get("revisit_when")
        if not revisit:
            continue
        try:
            if isinstance(revisit, date):
                d = revisit
            else:
                d = datetime.strptime(str(revisit).strip(), "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < today:
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="stale_decision",
                severity="warning",
                path=rel,
                message=f"revisit_when {d} has passed — review or update decision.",
            ))

    return issues


def check_asymmetric_conflict(vault: Path | None = None) -> list[dict]:
    """A→B 선언됐지만 B→A 미선언인 비대칭 conflicts_with를 보고한다."""
    vault = vault or get_vault_path()
    issues = []

    # 파일별 conflicts_with 수집
    declared: dict[str, set[str]] = {}
    for f in _decision_files(vault):
        text = f.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(text)
        rel = str(f.relative_to(vault))
        raw = meta.get("conflicts_with", [])
        if isinstance(raw, str):
            raw = [raw]
        declared[rel] = {str(c).strip() for c in (raw or [])}

    for path_a, conflicts in declared.items():
        for path_b in conflicts:
            b_conflicts = declared.get(path_b, set())
            if path_a not in b_conflicts:
                issues.append(_issue(
                    rule="asymmetric_conflict",
                    severity="warning",
                    path=path_a,
                    message=(
                        f"{path_a} declares conflicts_with {path_b!r} "
                        f"but {path_b!r} does not reciprocate."
                    ),
                ))

    return issues


def check_index_drift(vault: Path | None = None) -> list[dict]:
    """01 Notes/Decision - *.md 파일 중 index.md Decisions 섹션에 누락된 것을 보고한다."""
    vault = vault or get_vault_path()
    issues = []

    index_path = vault / "index.md"
    if not index_path.exists():
        return []

    index_text = index_path.read_text(encoding="utf-8")

    for f in _decision_files(vault):
        stem = f.stem  # e.g. "Decision - A"
        # [[Decision - A]] 또는 Decision - A 형태로 index에 있으면 OK
        if stem not in index_text:
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="index_drift",
                severity="info",
                path=rel,
                message=f"{stem!r} is not referenced in index.md Decisions section.",
            ))

    return issues


def check_superseded_dangling(vault: Path | None = None) -> list[dict]:
    """## Superseded by 헤딩이 있지만 frontmatter decision_status 없는 결정을 보고한다."""
    vault = vault or get_vault_path()
    issues = []
    superseded_pattern = re.compile(r"^##\s+superseded\s+by", re.IGNORECASE | re.MULTILINE)

    for f in _decision_files(vault):
        text = f.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        if not superseded_pattern.search(body):
            continue
        if not meta.get("decision_status"):
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="superseded_dangling",
                severity="error",
                path=rel,
                message=(
                    "Has '## Superseded by' section but missing "
                    "frontmatter 'decision_status' field."
                ),
            ))

    return issues


def _all_notes(vault: Path) -> list[Path]:
    notes = vault / "01 Notes"
    if not notes.exists():
        return []
    return sorted(notes.glob("*.md"))


def check_missing_rationale(vault: Path | None = None) -> list[dict]:
    """Decision 파일에 ## Rationale 섹션이 없으면 보고한다."""
    vault = vault or get_vault_path()
    issues = []
    rationale_pattern = re.compile(r"^##\s+rationale", re.IGNORECASE | re.MULTILINE)

    for f in _decision_files(vault):
        text = f.read_text(encoding="utf-8")
        _, body = _parse_frontmatter(text)
        if not rationale_pattern.search(body):
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="missing_rationale",
                severity="warning",
                path=rel,
                message="Decision file is missing a '## Rationale' section.",
            ))

    return issues


def check_missing_created(vault: Path | None = None) -> list[dict]:
    """frontmatter created 필드가 없는 Decision/Note를 보고한다."""
    vault = vault or get_vault_path()
    issues = []

    for f in _all_notes(vault):
        text = f.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(text)
        if not meta.get("created"):
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="missing_created",
                severity="info",
                path=rel,
                message="Missing frontmatter 'created' date field.",
            ))

    return issues


def check_missing_tags(vault: Path | None = None) -> list[dict]:
    """frontmatter tags가 없거나 비어있는 Decision/Note를 보고한다."""
    vault = vault or get_vault_path()
    issues = []

    for f in _all_notes(vault):
        text = f.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(text)
        tags = meta.get("tags")
        if not tags or (isinstance(tags, list) and len(tags) == 0):
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="missing_tags",
                severity="info",
                path=rel,
                message="Missing or empty frontmatter 'tags' field.",
            ))

    return issues


def check_dangling_candidate(vault: Path | None = None) -> list[dict]:
    """decision_candidates 있고 status가 draft인 노트를 보고한다."""
    vault = vault or get_vault_path()
    issues = []

    for f in _all_notes(vault):
        text = f.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(text)
        candidates = meta.get("decision_candidates")
        if not candidates or (isinstance(candidates, list) and len(candidates) == 0):
            continue
        if str(meta.get("status", "")).lower() == "draft":
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="dangling_candidate",
                severity="warning",
                path=rel,
                message=(
                    f"Has {len(candidates)} decision_candidate(s) but status is still 'draft' — "
                    "consider deciding or archiving."
                ),
            ))

    return issues


_TIME_HINT_PATTERN = re.compile(r"주|개월|년|분기|반기", re.IGNORECASE)
_DATE_PATTERN_LINT = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_LINT_IGNORE_PATTERN = re.compile(r"#\s*lint-ignore:\s*(\S+)")


def _has_lint_ignore(body: str, rule: str) -> bool:
    for m in _LINT_IGNORE_PATTERN.finditer(body):
        if rule in m.group(1):
            return True
    return False


def check_revisit_when_time_hint(vault: Path | None = None) -> list[dict]:
    """revisit_when에 시간 키워드는 있지만 절대 날짜(20XX-XX-XX) 없는 결정을 보고한다."""
    vault = vault or get_vault_path()
    issues = []

    for f in _all_notes(vault):
        text = f.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        if _has_lint_ignore(body, "revisit_when_time_hint"):
            continue
        revisit = str(meta.get("revisit_when", "")).strip()
        if not revisit:
            continue
        if _TIME_HINT_PATTERN.search(revisit) and not _DATE_PATTERN_LINT.search(revisit):
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="revisit_when_time_hint",
                severity="warning",
                path=rel,
                message=f"revisit_when {revisit!r} has time hint but no absolute date (YYYY-MM-DD).",
            ))

    return issues


def check_orphaned_note(vault: Path | None = None) -> list[dict]:
    """type=note + status≠draft + mocs/sources 모두 비어있는 노트를 보고한다."""
    vault = vault or get_vault_path()
    issues = []

    for f in _all_notes(vault):
        text = f.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        if _has_lint_ignore(body, "orphaned_note"):
            continue
        if meta.get("type") != "note":
            continue
        if str(meta.get("status", "")).lower() == "draft":
            continue
        mocs = meta.get("mocs") or []
        sources = meta.get("sources") or []
        has_mocs = isinstance(mocs, list) and len(mocs) > 0 or (bool(mocs) and not isinstance(mocs, list))
        has_sources = isinstance(sources, list) and len(sources) > 0 or (bool(sources) and not isinstance(sources, list))
        if not has_mocs and not has_sources:
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="orphaned_note",
                severity="info",
                path=rel,
                message="Note has no mocs or sources links — may be isolated.",
            ))

    return issues


def check_inbox_aging(vault: Path | None = None) -> list[dict]:
    """00 Inbox/ 파일 중 mtime이 LINT_INBOX_AGING_DAYS일+ 경과한 것을 보고한다."""
    import time as _time

    vault = vault or get_vault_path()
    issues = []
    threshold_days = int(os.environ.get("LINT_INBOX_AGING_DAYS", "30"))
    threshold_secs = threshold_days * 24 * 3600
    now = _time.time()

    inbox = vault / "00 Inbox"
    if not inbox.exists():
        return []

    for f in sorted(inbox.glob("*.md")):
        age = now - f.stat().st_mtime
        if age >= threshold_secs:
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="inbox_aging",
                severity="info",
                path=rel,
                message=f"Inbox file has been unprocessed for {int(age // 86400)} days.",
            ))

    return issues


def check_unprocessed_candidate(vault: Path | None = None) -> list[dict]:
    """decision_candidates 있고 mtime이 180일+ 경과한 노트를 보고한다."""
    import time as _time

    vault = vault or get_vault_path()
    issues = []
    threshold_days = int(os.environ.get("LINT_CANDIDATE_AGING_DAYS", "180"))
    threshold_secs = threshold_days * 24 * 3600
    now = _time.time()

    for f in _all_notes(vault):
        text = f.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        if _has_lint_ignore(body, "unprocessed_candidate"):
            continue
        candidates = meta.get("decision_candidates")
        if not candidates or (isinstance(candidates, list) and len(candidates) == 0):
            continue
        age = now - f.stat().st_mtime
        if age >= threshold_secs:
            rel = str(f.relative_to(vault))
            issues.append(_issue(
                rule="unprocessed_candidate",
                severity="warning",
                path=rel,
                message=(
                    f"Has {len(candidates)} decision_candidate(s) but not updated "
                    f"for {int(age // 86400)} days."
                ),
            ))

    return issues


def run_lint(vault: Path | None = None, scope: str = "production_safety") -> dict:
    """지정된 scope의 lint 룰을 실행하고 결과를 반환한다."""
    vault = vault or get_vault_path()

    production_safety_rules = [
        check_stale_decision,
        check_asymmetric_conflict,
        check_index_drift,
        check_superseded_dangling,
    ]

    writing_hygiene_rules = [
        check_missing_rationale,
        check_missing_created,
        check_missing_tags,
        check_dangling_candidate,
        check_revisit_when_time_hint,
        check_orphaned_note,
        check_inbox_aging,
        check_unprocessed_candidate,
    ]

    if scope == "production_safety":
        rules = production_safety_rules
    elif scope == "writing_hygiene":
        rules = writing_hygiene_rules
    elif scope == "all":
        rules = production_safety_rules + writing_hygiene_rules
    else:
        rules = production_safety_rules

    issues: list[dict] = []
    for rule_fn in rules:
        issues.extend(rule_fn(vault))

    by_rule: dict[str, int] = {}
    for issue in issues:
        by_rule[issue["rule"]] = by_rule.get(issue["rule"], 0) + 1

    return {
        "issues": issues,
        "summary": {"total": len(issues), "by_rule": by_rule},
    }
