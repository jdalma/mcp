"""Lint 3룰: asymmetric_conflict / stale_decision / superseded_dangling.

advisor.py와의 역할 분리:
- advisor.detect_conflicts: 양방향 conflicts_with 선언만 conflict로 인정.
- lint.find_asymmetric_conflicts: 단방향 선언 + title collision을 issue로 보고.

대상: human_reviewed=1, type=decision, 00 Inbox/·99 Archive/ 제외.
룰 내부에서 추가 필터(superseded 제외 등) 적용.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from vault_decision.advisor import parse_conflicts_list, parse_date

SUPERSEDED_HEADING_RE = re.compile(
    r"^##\s+Superseded\s+by", re.IGNORECASE | re.MULTILINE
)


def _fetch_reviewable_decisions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """human_reviewed=1, type=decision, 00 Inbox/·99 Archive/ 제외."""
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT path, title, type, status, decision_status,
                   human_reviewed, revisit_when, conflicts_with,
                   body, metadata_json
            FROM docs
            WHERE human_reviewed = 1
              AND type = 'decision'
              AND path NOT LIKE '00 Inbox/%'
              AND path NOT LIKE '99 Archive/%'
            """
        ).fetchall()
    finally:
        conn.row_factory = prev


def _attach_metadata(rows: list[sqlite3.Row]) -> list[dict]:
    """sqlite3.Row → plain dict, metadata_json을 'metadata' 키로 파싱."""
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        raw = d.pop("metadata_json", None)
        try:
            d["metadata"] = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
        out.append(d)
    return out


def find_asymmetric_conflicts(rows: list[dict]) -> list[dict]:
    """단방향 conflicts_with + title collision issue 보고."""
    active = [r for r in rows if r.get("decision_status") != "superseded"]

    by_title: dict[str, list[dict]] = {}
    for r in active:
        by_title.setdefault(r["title"], []).append(r)

    issues: list[dict] = []

    for title, group in by_title.items():
        if len(group) > 1:
            for r in group:
                issues.append({
                    "rule": "asymmetric_conflict",
                    "severity": "warning",
                    "path": r["path"],
                    "title": title,
                    "detail": (
                        f"title collision: {len(group)} notes share title "
                        f"'{title}' (wikilink ambiguity)"
                    ),
                })

    for r in active:
        my_title = r["title"]
        for other in parse_conflicts_list(r["metadata"].get("conflicts_with")):
            if other not in by_title:
                continue
            other_declares_back = any(
                my_title in parse_conflicts_list(o["metadata"].get("conflicts_with"))
                for o in by_title[other]
            )
            if not other_declares_back:
                issues.append({
                    "rule": "asymmetric_conflict",
                    "severity": "warning",
                    "path": r["path"],
                    "title": my_title,
                    "detail": (
                        f"declares conflict with '{other}', "
                        f"but '{other}' does not reciprocate"
                    ),
                })
    return issues


def find_stale_decisions(rows: list[dict], today: date) -> list[dict]:
    """status=decided & not superseded인 결정 중 revisit_when 만료."""
    issues: list[dict] = []
    for r in rows:
        if r.get("status") != "decided":
            continue
        if r.get("decision_status") == "superseded":
            continue
        revisit = parse_date(r.get("revisit_when"))
        if revisit and revisit < today:
            issues.append({
                "rule": "stale_decision",
                "severity": "warning",
                "path": r["path"],
                "title": r["title"],
                "detail": (
                    f"revisit_when={r['revisit_when']} is in the past "
                    f"(today={today})"
                ),
            })
    return issues


def find_superseded_dangling(rows: list[dict]) -> list[dict]:
    """본문 `## Superseded by` 있지만 decision_status != superseded."""
    issues: list[dict] = []
    for r in rows:
        if r.get("decision_status") == "superseded":
            continue
        if SUPERSEDED_HEADING_RE.search(r.get("body") or ""):
            issues.append({
                "rule": "superseded_dangling",
                "severity": "warning",
                "path": r["path"],
                "title": r["title"],
                "detail": (
                    "body has '## Superseded by' heading but "
                    "decision_status != 'superseded'"
                ),
            })
    return issues


def _build_summary(issues: list[dict]) -> str:
    if not issues:
        return "0 issues found"
    by_rule: dict[str, int] = {}
    for i in issues:
        by_rule[i["rule"]] = by_rule.get(i["rule"], 0) + 1
    parts = sorted(f"{n} {rule}" for rule, n in by_rule.items())
    return f"{len(issues)} issues found ({', '.join(parts)})"


def lint(conn: sqlite3.Connection, *, today: date | None = None) -> dict:
    """3룰을 모두 돌려 issue 리스트 + summary 반환."""
    if today is None:
        today = date.today()
    rows = _fetch_reviewable_decisions(conn)
    rows_with_meta = _attach_metadata(rows)

    issues = (
        find_asymmetric_conflicts(rows_with_meta)
        + find_stale_decisions(rows_with_meta, today)
        + find_superseded_dangling(rows_with_meta)
    )
    return {"issues": issues, "summary": _build_summary(issues)}
