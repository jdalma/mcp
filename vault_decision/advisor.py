"""권위 판정 + 추천 액션 산출.

searcher.search()가 반환한 top-15 hit을 받아:
1) 단일 hit을 7분류로 classify
2) bucket으로 묶기
3) 양방향 conflicts_with 위반 감지
4) top-level authority_level + recommended_action 산출 (동일 우선순위)
5) basis 빌드 (max_results 상한)
6) warnings / next_steps 조립

LOC 게이트 없음 (2026-05-14 결정). 동작·의미 기준만.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from vault_decision.searcher import search

AUTHORITY_PRIORITY: tuple[str, ...] = (
    "decided_conflicting",
    "decided_applicable",
    "decided_stale",
    "note_only",
    "historical_negative",
    "candidate",
)


def parse_conflicts_list(value: Any) -> list[str]:
    """frontmatter conflicts_with가 list/str 양쪽일 수 있음 → list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def parse_date(value: Any) -> date | None:
    """YYYY-MM-DD 문자열을 date로. 빈 값/잘못된 포맷은 None."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError):
        return None


def classify_authority(hit: dict, today: date) -> str:
    """단일 hit의 authority_level. parent_plan §6.3."""
    path = hit["path"]
    if path.startswith("00 Inbox/"):
        return "excluded"
    if path.startswith("99 Archive/"):
        return "historical_negative"
    if not hit["human_reviewed"]:
        return "note_only"
    if hit["type"] == "decision":
        if hit["status"] != "decided":
            return "decided_stale"
        if hit["decision_status"] == "superseded":
            return "decided_stale"
        revisit = parse_date(hit["metadata"].get("revisit_when"))
        if revisit and revisit < today:
            return "decided_stale"
        return "decided_applicable"
    if hit["type"] == "note":
        return "note_only"
    return "candidate"


def detect_conflicts(applicable: list[dict]) -> set[frozenset[str]]:
    """양방향 conflicts_with 선언이 있는 active decision 쌍 (frozenset 집합)."""
    by_title = {
        h["title"]: set(parse_conflicts_list(h["metadata"].get("conflicts_with")))
        for h in applicable
    }
    pairs: set[frozenset[str]] = set()
    for a, a_conflicts in by_title.items():
        for b in a_conflicts:
            if b in by_title and a in by_title[b]:
                pairs.add(frozenset({a, b}))
    return pairs


def aggregate_authority(buckets: dict[str, list]) -> str:
    """여러 hit를 단일 top-level authority_level로 압축. recommend_action과 동일 우선순위."""
    for level in AUTHORITY_PRIORITY:
        if buckets.get(level):
            return level
    return "none"


def recommend_action(buckets: dict[str, list]) -> str:
    if buckets.get("decided_conflicting"):
        return "ask_user"
    if buckets.get("decided_applicable"):
        return "proceed"
    if buckets.get("decided_stale"):
        return "ask_confirmation"
    if buckets.get("note_only"):
        return "answer_with_citation"
    if buckets.get("historical_negative"):
        return "do_not_proceed"
    if buckets.get("candidate"):
        return "ask_user"
    return "ask_user"


def _bucketize(hits: Iterable[dict], today: date) -> dict[str, list[dict]]:
    """hit 리스트 → {authority_level: [hit, ...]}. excluded는 버림."""
    buckets: dict[str, list[dict]] = {}
    for h in hits:
        level = classify_authority(h, today)
        if level == "excluded":
            continue
        buckets.setdefault(level, []).append(h)
    return buckets


def _promote_conflicts(buckets: dict[str, list[dict]]) -> set[frozenset[str]]:
    """decided_applicable 안에서 양방향 conflict가 있으면 decided_conflicting으로 승격."""
    applicable = buckets.get("decided_applicable", [])
    if len(applicable) < 2:
        return set()
    pairs = detect_conflicts(applicable)
    if not pairs:
        return set()
    conflicting_titles: set[str] = set()
    for pair in pairs:
        conflicting_titles.update(pair)
    promoted: list[dict] = []
    kept: list[dict] = []
    for h in applicable:
        if h["title"] in conflicting_titles:
            promoted.append(h)
        else:
            kept.append(h)
    buckets["decided_applicable"] = kept
    if promoted:
        buckets.setdefault("decided_conflicting", []).extend(promoted)
    return pairs


def _build_basis(buckets: dict[str, list[dict]], max_results: int) -> list[dict]:
    """우선순위 순으로 basis를 채우고 max_results로 절단."""
    basis: list[dict] = []
    for level in AUTHORITY_PRIORITY:
        for h in buckets.get(level, []):
            if len(basis) >= max_results:
                return basis
            excerpt = (h.get("body") or "")[:200]
            if len(h.get("body") or "") > 200:
                excerpt += "..."
            basis.append({
                "path": h["path"],
                "title": h["title"],
                "authority_level": level,
                "citation": h["path"],
                "excerpt": excerpt,
            })
    return basis


def _compose_messages(
    top_level: str, pairs: set[frozenset[str]]
) -> tuple[list[str], list[str]]:
    """§2.1 warnings/next_steps 조립 표."""
    warnings: list[str] = []
    next_steps: list[str] = []
    if top_level == "none":
        warnings.append("No matching vault entries")
        next_steps.append("Refine the question or check 00 Inbox/ for unreviewed candidates")
    elif top_level == "decided_conflicting":
        pair_strs = sorted(" <-> ".join(sorted(p)) for p in pairs)
        warnings.append(
            f"Found {len(pairs)} conflicting active decision pair(s): {pair_strs}"
        )
        next_steps.append(
            "Resolve the conflict before acting; ask the user which decision is current"
        )
    elif top_level == "decided_applicable":
        next_steps.append("Follow the cited decision")
    elif top_level == "decided_stale":
        warnings.append(
            "Only stale decisions match (status≠decided / superseded / revisit_when expired)"
        )
        next_steps.append("Confirm with user whether the stale decision is still valid")
    elif top_level == "note_only":
        next_steps.append("Cite the note; no authoritative decision binds the action")
    elif top_level == "historical_negative":
        warnings.append("Matches an archived (rejected) pattern")
        next_steps.append("Do not proceed with this approach")
    elif top_level == "candidate":
        warnings.append("Classification fallback — frontmatter incomplete")
        next_steps.append("Inspect the file directly with read_decision()")
    return warnings, next_steps


def advise(
    conn,
    question: str,
    *,
    max_results: int = 5,
    today: date | None = None,
) -> dict:
    """질문 → 권위 판정 + 추천 액션."""
    if today is None:
        today = date.today()

    hits = search(conn, question, max_results=15)
    buckets = _bucketize(hits, today)
    pairs = _promote_conflicts(buckets)

    top_level = aggregate_authority(buckets)
    action = recommend_action(buckets)
    basis = _build_basis(buckets, max_results)
    warnings, next_steps = _compose_messages(top_level, pairs)

    return {
        "authority_level": top_level,
        "recommended_action": action,
        "basis": basis,
        "warnings": warnings,
        "next_steps": next_steps,
    }
