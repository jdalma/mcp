"""Tests for tools_extra module."""


def test_get_stats_with_data():
    from tools_extra import get_stats

    class FakeCollection:
        def get(self, include=None):
            return {
                "ids": ["doc1", "doc2", "doc3"],
                "metadatas": [
                    {"type": "decision", "status": "decided"},
                    {"type": "decision", "status": "draft"},
                    {"type": "note", "status": "confirmed"},
                ],
            }

    result = get_stats(FakeCollection())
    assert "Total documents: 3" in result
    assert "decision: 2" in result
    assert "note: 1" in result


def test_get_stats_empty():
    from tools_extra import get_stats

    class FakeCollection:
        def get(self, include=None):
            return {"ids": [], "metadatas": []}

    result = get_stats(FakeCollection())
    assert "No documents indexed" in result


def test_decision_timeline():
    from tools_extra import get_decision_timeline

    class FakeCollection:
        def get(self, where=None, include=None):
            return {
                "ids": ["d1", "d2"],
                "metadatas": [
                    {"type": "decision", "title": "Decision A", "created": "2026-04-10", "status": "decided"},
                    {"type": "decision", "title": "Decision B", "created": "2026-04-15", "status": "draft"},
                ],
            }

    result = get_decision_timeline(FakeCollection())
    assert "Decision B" in result
    assert "Decision A" in result
    # B (2026-04-15) should come before A (2026-04-10) in reverse chrono
    assert result.index("Decision B") < result.index("Decision A")


def test_stats_asymmetric_conflicts():
    """get_stats 응답에 asymmetric_conflicts 카운트가 포함되어야 한다."""
    import importlib

    import indexer

    # 비대칭 목록을 강제로 세팅
    indexer._asymmetric_conflicts = ["01 Notes/Decision - A.md"]

    from tools_extra import get_stats

    class FakeCollection:
        def get(self, include=None):
            return {
                "ids": ["doc1"],
                "metadatas": [{"type": "decision", "status": "decided"}],
            }

    result = get_stats(FakeCollection())
    assert "asymmetric_conflicts: 1" in result, (
        f"asymmetric_conflicts 카운트 미포함. result={result!r}"
    )

    # 정리
    indexer._asymmetric_conflicts = []


def test_decision_timeline_empty():
    from tools_extra import get_decision_timeline

    class FakeCollection:
        def get(self, where=None, include=None):
            return {"ids": [], "metadatas": []}

    result = get_decision_timeline(FakeCollection())
    assert "No decisions found" in result
