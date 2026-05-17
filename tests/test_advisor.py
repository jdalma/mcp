"""Phase 2 P2-1: advisor 순수 함수 단위 테스트.

advise() 전체 path(searcher + bge-m3)는 통합 게이트(P2-4/5/6)의 책임.
여기서는 classify_authority / detect_conflicts / aggregate_authority /
recommend_action / _bucketize / _promote_conflicts / _build_basis /
_compose_messages만 직접 호출.
"""

from __future__ import annotations

from datetime import date

import pytest

from vault_decision.advisor import (
    AUTHORITY_PRIORITY,
    _bucketize,
    _build_basis,
    _compose_messages,
    _promote_conflicts,
    aggregate_authority,
    classify_authority,
    detect_conflicts,
    parse_conflicts_list,
    parse_date,
    recommend_action,
)

TODAY = date(2026, 5, 14)


def _hit(
    *,
    path: str,
    title: str = "T",
    type: str | None = "decision",
    status: str | None = "decided",
    decision_status: str | None = None,
    human_reviewed: bool = True,
    body: str = "body",
    metadata: dict | None = None,
) -> dict:
    return {
        "path": path,
        "title": title,
        "type": type,
        "status": status,
        "decision_status": decision_status,
        "human_reviewed": human_reviewed,
        "path_role": "active_decision",
        "context": None,
        "body": body,
        "score_bm25": None,
        "rank_bm25": None,
        "score_embedding": None,
        "rank_embedding": None,
        "score_rrf": 1.0,
        "metadata": metadata or {},
    }


# --- parse_conflicts_list ---


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, []),
        ("", []),
        ([], []),
        (["A", "B"], ["A", "B"]),
        ("A, B, C", ["A", "B", "C"]),
        ("  A  ", ["A"]),
        (123, []),
    ],
)
def test_parse_conflicts_list(value, expected):
    assert parse_conflicts_list(value) == expected


# --- parse_date ---


def test_parse_date_valid():
    assert parse_date("2026-05-14") == date(2026, 5, 14)


@pytest.mark.parametrize("value", [None, "", "not-a-date", "2026/05/14", 12345])
def test_parse_date_invalid(value):
    assert parse_date(value) is None


def test_parse_date_passthrough_date_object():
    d = date(2020, 1, 1)
    assert parse_date(d) == d


# --- classify_authority (단일 hit 7 케이스) ---


def test_classify_decided_applicable():
    h = _hit(
        path="01 Notes/Decision - X.md",
        type="decision",
        status="decided",
        metadata={"revisit_when": "2099-01-01"},
    )
    assert classify_authority(h, TODAY) == "decided_applicable"


def test_classify_decided_stale_by_revisit_expired():
    h = _hit(
        path="01 Notes/Decision - X.md",
        type="decision",
        status="decided",
        metadata={"revisit_when": "2020-01-01"},
    )
    assert classify_authority(h, TODAY) == "decided_stale"


def test_classify_decided_stale_by_superseded():
    h = _hit(
        path="01 Notes/Decision - X.md",
        type="decision",
        status="decided",
        decision_status="superseded",
    )
    assert classify_authority(h, TODAY) == "decided_stale"


def test_classify_decided_stale_by_status_not_decided():
    h = _hit(
        path="01 Notes/Decision - X.md", type="decision", status="draft"
    )
    assert classify_authority(h, TODAY) == "decided_stale"


def test_classify_note_only():
    h = _hit(path="01 Notes/X.md", type="note", status=None)
    assert classify_authority(h, TODAY) == "note_only"


def test_classify_historical_negative():
    h = _hit(path="99 Archive/Old.md", type="decision")
    assert classify_authority(h, TODAY) == "historical_negative"


def test_classify_excluded_inbox():
    h = _hit(path="00 Inbox/Draft.md", type="decision")
    assert classify_authority(h, TODAY) == "excluded"


def test_classify_human_reviewed_false_demoted_to_note_only():
    h = _hit(
        path="01 Notes/Decision - X.md",
        type="decision",
        status="decided",
        human_reviewed=False,
    )
    assert classify_authority(h, TODAY) == "note_only"


def test_classify_candidate_fallback_on_unknown_type():
    h = _hit(path="01 Notes/X.md", type="unknown", status=None)
    assert classify_authority(h, TODAY) == "candidate"


# --- detect_conflicts (양방향 vs 단방향) ---


def test_detect_conflicts_bilateral():
    a = _hit(path="01 Notes/Decision - A.md", title="A", metadata={"conflicts_with": ["B"]})
    b = _hit(path="01 Notes/Decision - B.md", title="B", metadata={"conflicts_with": ["A"]})
    pairs = detect_conflicts([a, b])
    assert pairs == {frozenset({"A", "B"})}


def test_detect_conflicts_unilateral_ignored():
    a = _hit(path="01 Notes/Decision - A.md", title="A", metadata={"conflicts_with": ["B"]})
    b = _hit(path="01 Notes/Decision - B.md", title="B", metadata={"conflicts_with": []})
    assert detect_conflicts([a, b]) == set()


def test_detect_conflicts_dedup_with_frozenset():
    a = _hit(path="01 Notes/Decision - A.md", title="A", metadata={"conflicts_with": ["B"]})
    b = _hit(path="01 Notes/Decision - B.md", title="B", metadata={"conflicts_with": ["A"]})
    pairs = detect_conflicts([a, b])
    assert len(pairs) == 1


# --- aggregate_authority + recommend_action (4 aggregation 케이스) ---


def test_aggregate_and_action_decided_conflicting():
    buckets = {"decided_conflicting": [object()], "decided_applicable": [object()]}
    assert aggregate_authority(buckets) == "decided_conflicting"
    assert recommend_action(buckets) == "ask_user"


def test_aggregate_and_action_mixed_applicable_and_stale():
    buckets = {
        "decided_applicable": [object()],
        "decided_stale": [object(), object()],
    }
    assert aggregate_authority(buckets) == "decided_applicable"
    assert recommend_action(buckets) == "proceed"


def test_aggregate_and_action_empty_buckets():
    assert aggregate_authority({}) == "none"
    assert recommend_action({}) == "ask_user"


def test_aggregate_and_action_candidate_only():
    buckets = {"candidate": [object()]}
    assert aggregate_authority(buckets) == "candidate"
    assert recommend_action(buckets) == "ask_user"


def test_priority_constant_matches_action_branches():
    assert AUTHORITY_PRIORITY == (
        "decided_conflicting",
        "decided_applicable",
        "decided_stale",
        "note_only",
        "historical_negative",
        "candidate",
    )


# --- _bucketize / _promote_conflicts / _build_basis / _compose_messages ---


def test_bucketize_drops_excluded():
    hits = [
        _hit(path="00 Inbox/Z.md"),
        _hit(path="01 Notes/Decision - X.md", title="X"),
    ]
    buckets = _bucketize(hits, TODAY)
    assert "excluded" not in buckets
    assert len(buckets.get("decided_applicable", [])) == 1


def test_promote_conflicts_moves_applicable_to_conflicting():
    a = _hit(path="01 Notes/Decision - A.md", title="A", metadata={"conflicts_with": ["B"]})
    b = _hit(path="01 Notes/Decision - B.md", title="B", metadata={"conflicts_with": ["A"]})
    buckets = {"decided_applicable": [a, b]}
    pairs = _promote_conflicts(buckets)
    assert pairs == {frozenset({"A", "B"})}
    assert buckets["decided_applicable"] == []
    assert {h["title"] for h in buckets["decided_conflicting"]} == {"A", "B"}


def test_promote_conflicts_keeps_non_conflicting_applicable():
    a = _hit(path="01 Notes/Decision - A.md", title="A", metadata={"conflicts_with": ["B"]})
    b = _hit(path="01 Notes/Decision - B.md", title="B", metadata={"conflicts_with": ["A"]})
    c = _hit(path="01 Notes/Decision - C.md", title="C")
    buckets = {"decided_applicable": [a, b, c]}
    _promote_conflicts(buckets)
    assert [h["title"] for h in buckets["decided_applicable"]] == ["C"]
    assert {h["title"] for h in buckets["decided_conflicting"]} == {"A", "B"}


def test_build_basis_truncates_to_max_results():
    buckets = {
        "decided_applicable": [
            _hit(path=f"01 Notes/Decision - {i}.md", title=str(i)) for i in range(10)
        ]
    }
    basis = _build_basis(buckets, max_results=3)
    assert len(basis) == 3
    assert all(item["authority_level"] == "decided_applicable" for item in basis)


def test_build_basis_priority_order():
    buckets = {
        "decided_applicable": [_hit(path="01 Notes/Decision - A.md", title="A")],
        "note_only": [_hit(path="01 Notes/N.md", title="N", type="note")],
        "historical_negative": [
            _hit(path="99 Archive/H.md", title="H", type="decision")
        ],
    }
    basis = _build_basis(buckets, max_results=10)
    levels = [item["authority_level"] for item in basis]
    assert levels == ["decided_applicable", "note_only", "historical_negative"]


def test_build_basis_excerpt_short_body_no_ellipsis():
    buckets = {"note_only": [_hit(path="01 Notes/X.md", title="X", body="short")]}
    basis = _build_basis(buckets, max_results=1)
    assert basis[0]["excerpt"] == "short"


def test_build_basis_excerpt_long_body_appends_ellipsis():
    long_body = "x" * 250
    buckets = {"note_only": [_hit(path="01 Notes/X.md", title="X", body=long_body)]}
    basis = _build_basis(buckets, max_results=1)
    assert basis[0]["excerpt"].endswith("...")
    assert len(basis[0]["excerpt"]) == 203


@pytest.mark.parametrize(
    "top_level, warning_present, next_step_present",
    [
        ("none", "No matching vault entries", "Refine the question"),
        ("decided_applicable", None, "Follow the cited decision"),
        ("decided_stale", "Only stale decisions match", "Confirm with user whether"),
        ("note_only", None, "Cite the note"),
        ("historical_negative", "archived (rejected) pattern", "Do not proceed"),
        ("candidate", "Classification fallback", "Inspect the file directly"),
    ],
)
def test_compose_messages_branches(top_level, warning_present, next_step_present):
    warnings, next_steps = _compose_messages(top_level, set())
    if warning_present is None:
        assert warnings == []
    else:
        assert any(warning_present in w for w in warnings)
    assert any(next_step_present in s for s in next_steps)


def test_compose_messages_conflicting_includes_pair_list():
    pairs = {frozenset({"A", "B"}), frozenset({"C", "D"})}
    warnings, next_steps = _compose_messages("decided_conflicting", pairs)
    assert any("Found 2 conflicting" in w for w in warnings)
    assert any("A <-> B" in w or "C <-> D" in w for w in warnings)
    assert any("Resolve the conflict" in s for s in next_steps)
