def test_format_results_with_matches():
    from searcher import format_results
    query_results = {
        "ids": [["doc1", "doc2"]],
        "documents": [["# Decision A\n\ncontent A", "# Note B\n\ncontent B"]],
        "metadatas": [[
            {"type": "decision", "status": "decided", "title": "Decision A",
             "tags": "architecture", "created": "2026-04-12",
             "file_path": "/vault/01 Notes/Decision - A.md",
             "relative_path": "01 Notes/Decision - A.md"},
            {"type": "note", "status": "confirmed", "title": "Note B",
             "tags": "engineering", "created": "2026-04-10",
             "file_path": "/vault/01 Notes/Note B.md",
             "relative_path": "01 Notes/Note B.md"},
        ]],
        "distances": [[0.25, 0.55]],
    }
    result = format_results("test query", query_results)
    assert "Decision A" in result
    assert "Note B" in result
    assert "01 Notes/Decision - A.md" in result
    assert "test query" in result


def test_format_results_empty():
    from searcher import format_results
    query_results = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    result = format_results("test query", query_results)
    assert "No relevant records" in result


def test_format_results_decision_boosted():
    """Decision 타입이 같은 distance의 note보다 상위에 나오는지 확인."""
    from searcher import format_results
    # 동일한 distance(0.4)를 가진 decision과 note
    query_results = {
        "ids": [["note1", "decision1"]],
        "documents": [["note content", "decision content"]],
        "metadatas": [[
            {"type": "note", "status": "confirmed", "title": "Note First",
             "tags": "", "created": "2026-04-10",
             "file_path": "/vault/note.md", "relative_path": "note.md"},
            {"type": "decision", "status": "confirmed", "title": "Decision Second",
             "tags": "", "created": "2026-04-10",
             "file_path": "/vault/decision.md", "relative_path": "decision.md"},
        ]],
        "distances": [[0.4, 0.4]],
    }
    result = format_results("test", query_results)
    # Decision이 부스팅으로 상위에 와야 함
    decision_pos = result.index("Decision Second")
    note_pos = result.index("Note First")
    assert decision_pos < note_pos, "Decision should appear before Note due to type boosting"
    # Decision에 🔷 prefix 확인
    assert "\U0001f537" in result
    # Note에 📝 prefix 확인
    assert "\U0001f4dd" in result


def test_format_results_status_boosted():
    """decided status가 draft보다 상위인지 확인."""
    from searcher import format_results
    # 동일한 타입(decision), 동일한 distance, 다른 status
    query_results = {
        "ids": [["draft1", "decided1"]],
        "documents": [["draft content", "decided content"]],
        "metadatas": [[
            {"type": "decision", "status": "draft", "title": "Draft Decision",
             "tags": "", "created": "2026-04-10",
             "file_path": "/vault/draft.md", "relative_path": "draft.md"},
            {"type": "decision", "status": "decided", "title": "Decided Decision",
             "tags": "", "created": "2026-04-10",
             "file_path": "/vault/decided.md", "relative_path": "decided.md"},
        ]],
        "distances": [[0.3, 0.3]],
    }
    result = format_results("test", query_results)
    # decided가 draft보다 상위에 와야 함
    decided_pos = result.index("Decided Decision")
    draft_pos = result.index("Draft Decision")
    assert decided_pos < draft_pos, "Decided should appear before Draft due to status boosting"


def test_low_similarity_decision_is_not_boosted_over_relevant_note():
    """Semantic threshold prevents unrelated decisions from winning by type alone."""
    from searcher import rank_results

    query_results = {
        "ids": [["decision1", "note1"]],
        "documents": [["unrelated decision", "relevant note"]],
        "metadatas": [[
            {"type": "decision", "status": "decided", "title": "Unrelated Decision",
             "tags": "", "created": "2026-04-10",
             "file_path": "/vault/decision.md", "relative_path": "decision.md",
             "path_role": "active_decision"},
            {"type": "note", "status": "confirmed", "title": "Relevant Note",
             "tags": "", "created": "2026-04-10",
             "file_path": "/vault/note.md", "relative_path": "note.md",
             "path_role": "active_note"},
        ]],
        # decision similarity = 0.30, note similarity = 0.40
        "distances": [[0.70, 0.60]],
    }

    ranked = rank_results(query_results)

    assert ranked[0]["metadata"]["title"] == "Relevant Note"
