"""Tests for authority advice."""

from datetime import date


def _result(entries):
    return {
        "ids": [[entry["id"] for entry in entries]],
        "documents": [[entry["document"] for entry in entries]],
        "metadatas": [[entry["metadata"] for entry in entries]],
        "distances": [[entry["distance"] for entry in entries]],
    }


def _entry(doc_id, document, metadata, distance=0.25):
    base = {
        "title": doc_id,
        "type": "note",
        "status": "draft",
        "path_role": "active_note",
        "relative_path": doc_id,
        "content_hash": "hash",
    }
    base.update(metadata)
    return {"id": doc_id, "document": document, "metadata": base, "distance": distance}


def test_decision_tradeoff_returns_proceed_candidate():
    from advisor import build_advice

    results = _result([
        _entry(
            "01 Notes/Decision - Kafka.md",
            "# Decision: Kafka\n\n## Decision\nKafka 보류.\n\n## Rationale\nOutbox 우선.",
            {
                "title": "Decision - Kafka",
                "type": "decision",
                "status": "decided",
                "path_role": "active_decision",
            },
        )
    ])

    advice = build_advice("Kafka를 써야 할까?", results)

    assert advice["authority_level"] == "decided_applicable"
    assert advice["recommended_action"] == "proceed_candidate"
    assert advice["basis"][0]["title"] == "Decision - Kafka"


def test_note_only_tradeoff_requires_confirmation():
    from advisor import build_advice

    results = _result([
        _entry(
            "01 Notes/OMS.md",
            "# OMS\n\nKafka reliability analysis.",
            {"title": "OMS", "type": "note", "status": "confirmed", "path_role": "active_note"},
        )
    ])

    advice = build_advice("OMS는 Kafka를 써야 할까?", results)

    assert advice["authority_level"] == "note_only"
    assert advice["recommended_action"] == "ask_confirmation"


def test_note_only_fact_lookup_can_answer_with_citation():
    from advisor import build_advice

    results = _result([
        _entry(
            "01 Notes/OMS.md",
            "# OMS\n\nKafka reliability analysis.",
            {"title": "OMS", "type": "note", "status": "confirmed", "path_role": "active_note"},
        )
    ])

    advice = build_advice("OMS 관련 노트 목록 보여줘", results)

    assert advice["authority_level"] == "note_only"
    assert advice["recommended_action"] == "answer_with_citation"


def test_candidate_only_requires_confirmation():
    from advisor import build_advice

    results = _result([
        _entry(
            "01 Notes/Resilience.md",
            "# Resilience\n\ndecision candidate.",
            {
                "title": "Resilience",
                "type": "note",
                "status": "draft",
                "path_role": "active_note",
                "has_decision_candidates": True,
            },
        )
    ])

    advice = build_advice("Retry와 CB 순서를 정해야 할까?", results)

    assert advice["authority_level"] == "candidate"
    assert advice["recommended_action"] == "ask_confirmation"


def test_stale_decision_requires_confirmation():
    from advisor import build_advice

    results = _result([
        _entry(
            "01 Notes/Decision - Old.md",
            "# Decision: Old\n\n## Decision\nOld choice.",
            {
                "title": "Decision - Old",
                "type": "decision",
                "status": "decided",
                "path_role": "active_decision",
                "revisit_when": "2026-01-01",
            },
        )
    ])

    advice = build_advice("Old choice를 계속 써야 할까?", results, current_date=date(2026, 4, 28))

    assert advice["authority_level"] == "decided_stale"
    assert advice["recommended_action"] == "ask_confirmation"


def test_archive_negative_signal_does_not_grant_authority():
    from advisor import build_advice

    results = _result([
        _entry(
            "99 Archive/Decision - Old.md",
            "# Old\n\nThis approach was deprecated and rejected.",
            {
                "title": "Decision - Old",
                "type": "decision",
                "status": "archived",
                "path_role": "archive",
            },
        )
    ])

    advice = build_advice("Old approach를 채택할까?", results)

    assert advice["authority_level"] == "historical_negative"
    assert advice["recommended_action"] == "do_not_proceed"


def test_conflicting_decisions_require_user():
    from advisor import build_advice

    results = _result([
        _entry(
            "01 Notes/Decision - A.md",
            "# Decision: A\n\n## Decision\nA 채택.",
            {
                "title": "Decision - A",
                "type": "decision",
                "status": "decided",
                "path_role": "active_decision",
                "conflicts_with": "Decision - B",
            },
        ),
        _entry(
            "01 Notes/Decision - B.md",
            "# Decision: B\n\n## Decision\nB 채택.",
            {
                "title": "Decision - B",
                "type": "decision",
                "status": "decided",
                "path_role": "active_decision",
            },
            distance=0.26,
        ),
    ])

    advice = build_advice("A와 B 중 무엇을 채택해야 할까?", results)

    assert advice["authority_level"] == "decided_conflicting"
    assert advice["recommended_action"] == "ask_user"
