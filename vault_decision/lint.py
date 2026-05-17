"""Lint: asymmetric_conflict 1룰 (Phase 3.5 단순화).

advisor.py와의 역할 분리:
- advisor.detect_conflicts: 양방향 conflicts_with 선언만 conflict로 인정.
- lint.find_asymmetric_conflicts: 단방향 선언 + title collision을 issue로 보고.

대상: canonical=1, type=decision, 00 Inbox/·99 Archive/ 제외.

Phase 3.5 (2026-05-17): stale_decision / superseded_dangling 룰 폐기.
만료·superseded 개념 모두 frontmatter 단순화로 제거됨.
"""

from __future__ import annotations

import json
import sqlite3

from vault_decision.advisor import parse_conflicts_list


def _fetch_reviewable_decisions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """canonical=1, type=decision, 00 Inbox/·99 Archive/ 제외."""
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT path, title, type, canonical, conflicts_with,
                   body, metadata_json
            FROM docs
            WHERE canonical = 1
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
    by_title: dict[str, list[dict]] = {}
    for r in rows:
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

    for r in rows:
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


def _build_summary(issues: list[dict]) -> str:
    if not issues:
        return "0 issues found"
    by_rule: dict[str, int] = {}
    for i in issues:
        by_rule[i["rule"]] = by_rule.get(i["rule"], 0) + 1
    parts = sorted(f"{n} {rule}" for rule, n in by_rule.items())
    return f"{len(issues)} issues found ({', '.join(parts)})"


def lint(conn: sqlite3.Connection) -> dict:
    """1룰(asymmetric_conflict) 위반 + summary."""
    rows = _fetch_reviewable_decisions(conn)
    rows_with_meta = _attach_metadata(rows)
    issues = find_asymmetric_conflicts(rows_with_meta)
    return {"issues": issues, "summary": _build_summary(issues)}
