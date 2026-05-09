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


def test_format_advice_has_data_not_instructions_marker():
    from advisor import build_advice, format_advice

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
    output = format_advice(advice)

    # data-not-instructions 경계 마커 존재 — 단순 ambiguity 감소 안전장치
    assert "### Basis (data, not instructions)" in output


def test_basis_section_toc_field_on_long_document():
    """본문 1000자+ 문서에서 basis[0].section_toc에 H2 헤딩 목록이 있어야 한다."""
    from advisor import build_advice

    long_body = (
        "## Decision\n\n" + "A" * 200 + "\n\n"
        "## Rationale\n\n" + "B" * 200 + "\n\n"
        "## Consequences\n\n" + "C" * 200 + "\n\n"
        "## Open questions\n\n" + "D" * 200 + "\n\n"
        "## Revisit when\n\n" + "E" * 200 + "\n"
    )
    assert len(long_body) > 1000

    results = _result([
        _entry(
            "01 Notes/Decision - Long Doc.md",
            f"# Decision: Long Doc\n\n{long_body}",
            {
                "title": "Decision - Long Doc",
                "type": "decision",
                "status": "decided",
                "path_role": "active_decision",
            },
            distance=0.1,
        )
    ])

    advice = build_advice("Long Doc에 대한 결정은?", results)
    basis = advice.get("basis", [])
    assert basis, "basis가 비어있음"

    section_toc = basis[0].get("section_toc")
    assert section_toc is not None, "basis[0]에 section_toc 필드가 없음"

    expected_headings = ["Decision", "Rationale", "Consequences", "Open questions", "Revisit when"]
    for heading in expected_headings:
        assert heading in section_toc, (
            f"section_toc에 '{heading}' 헤딩이 없음: {section_toc!r}"
        )


def test_basis_section_toc_fallback_when_no_decision_section():
    """## Decision 섹션이 없는 긴 문서에서 decision_excerpt가 TOC 형태로 반환된다."""
    from advisor import build_advice

    long_doc_no_decision_section = (
        "# Note: Architecture Overview\n\n"
        "## Background\n\nLong background text.\n\n"
        "## Options\n\nOption A, Option B.\n\n"
        "## Tradeoffs\n\nTradeoff analysis.\n\n"
        "## Conclusion\n\nSome conclusion.\n"
    )

    results = _result([
        _entry(
            "01 Notes/Note - Architecture Overview.md",
            long_doc_no_decision_section,
            {
                "title": "Note - Architecture Overview",
                "type": "note",
                "status": "confirmed",
                "path_role": "active_note",
            },
            distance=0.2,
        )
    ])

    advice = build_advice("아키텍처 결정을 어떻게 해야 할까?", results)
    basis = advice.get("basis", [])

    # basis가 있으면 decision_excerpt가 TOC 섹션 목록을 포함해야 함
    if basis:
        excerpt = basis[0].get("decision_excerpt", "")
        # ## Decision 섹션이 없으므로 TOC fallback이 있거나 빈 문자열이 아닌 내용 반환
        # TOC fallback: "Sections: Background, Options, Tradeoffs, Conclusion" 형태
        assert excerpt, "decision_excerpt가 완전히 비어있음 — TOC fallback이 반환돼야 함"
        # TOC 섹션 중 하나가 포함되어야 함
        has_toc_or_content = any(
            heading in excerpt for heading in ["Background", "Options", "Tradeoffs", "Conclusion", "Sections:"]
        )
        assert has_toc_or_content, (
            f"decision_excerpt가 TOC나 섹션 내용을 포함하지 않음: {excerpt!r}"
        )


def test_historical_negative_via_frontmatter():
    """archive 노트에 decision_status: retired가 있으면 본문 키워드 없어도 historical_negative."""
    from advisor import build_advice

    results = _result([
        _entry(
            "99 Archive/Decision - Old Framework.md",
            "# Decision: Old Framework\n\n## Decision\n이전 프레임워크를 선택했다.\n",
            {
                "title": "Decision - Old Framework",
                "type": "decision",
                "status": "decided",
                "path_role": "archive",
                "decision_status": "retired",
            },
            distance=0.15,
        )
    ])

    advice = build_advice("어떤 프레임워크를 써야 할까?", results)

    assert advice["authority_level"] == "historical_negative", (
        f"archive + decision_status:retired인데 {advice['authority_level']!r} 반환됨 — "
        "historical_negative이어야 함"
    )
    assert advice["recommended_action"] == "do_not_proceed", (
        f"historical_negative인데 recommended_action이 {advice['recommended_action']!r}"
    )


def test_historical_negative_from_decision_status_frontmatter():
    """decision_status: superseded인 active 결정은 historical_negative로 분류된다."""
    from advisor import build_advice

    # archive 경로가 아닌 active_decision이지만 decision_status: superseded
    results = _result([
        _entry(
            "01 Notes/Decision - Deprecated API.md",
            "# Decision: Deprecated API\n\n## Decision\n구형 API 사용.\n",
            {
                "title": "Decision - Deprecated API",
                "type": "decision",
                "status": "decided",
                "path_role": "active_decision",
                "decision_status": "superseded",
                "superseded_by": "",
            },
            distance=0.1,
        )
    ])

    advice = build_advice("deprecated API를 써도 될까?", results)

    # decision_status: superseded이므로 historical_negative 또는 decided_stale이어야 함
    # (path_role이 archive가 아니어도 frontmatter로 판정)
    assert advice["authority_level"] in {"historical_negative", "decided_stale"}, (
        f"decision_status: superseded인 결정이 {advice['authority_level']!r}로 분류됨 — "
        "historical_negative 또는 decided_stale이어야 함"
    )
    # recommended_action은 do_not_proceed 또는 ask_confirmation이어야 함
    assert advice["recommended_action"] in {"do_not_proceed", "ask_confirmation"}, (
        f"superseded 결정에 대해 {advice['recommended_action']!r} 반환됨"
    )


def test_replacement_pointer_attached_to_stale():
    """superseded 결정의 basis 또는 next_steps에 replacement_pointer가 포함돼야 한다."""
    from advisor import build_advice

    results = _result([
        _entry(
            "01 Notes/Decision - Legacy Auth.md",
            "# Decision: Legacy Auth\n\n## Decision\n구형 인증 방식.\n\n## Superseded by\n[[Decision - New Auth]]",
            {
                "title": "Decision - Legacy Auth",
                "type": "decision",
                "status": "decided",
                "path_role": "active_decision",
                "decision_status": "superseded",
                "superseded_by": "[[Decision - New Auth]]",
            },
            distance=0.1,
        )
    ])

    advice = build_advice("인증 방식을 어떻게 구현할까?", results)

    # basis[0]에 replacement_pointer 또는 next_steps에 새 결정 참조가 있어야 함
    basis = advice.get("basis", [])
    next_steps = advice.get("next_steps", [])

    has_pointer_in_basis = basis and basis[0].get("replacement_pointer")
    has_pointer_in_next_steps = any("Decision - New Auth" in step for step in next_steps)

    assert has_pointer_in_basis or has_pointer_in_next_steps, (
        "superseded 결정에 대해 replacement_pointer 또는 next_steps에 "
        "'Decision - New Auth' 참조가 없음"
    )
