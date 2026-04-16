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
