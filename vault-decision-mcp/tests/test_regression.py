"""Regression set — baseline captured 2026-05-08.

영구 ChromaDB(.chroma/)와 실제 KR-SBERT 임베딩을 사용한다.
vault가 없거나 인덱스가 비어 있으면 전체 스킵.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "regression_queries.yaml"


def _load_cases():
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["cases"]


def _is_index_available() -> bool:
    try:
        import chromadb
        from config import get_chroma_dir, COLLECTION_NAME

        client = chromadb.PersistentClient(path=str(get_chroma_dir()))
        col = client.get_collection(COLLECTION_NAME)
        return col.count() > 0
    except Exception:
        return False


# session-scope로 collection을 한 번만 로드 (임베딩 모델 로드 비용 절감)
@pytest.fixture(scope="session")
def collection():
    import chromadb
    from config import get_chroma_dir, COLLECTION_NAME

    client = chromadb.PersistentClient(path=str(get_chroma_dir()))
    return client.get_collection(COLLECTION_NAME)


@pytest.mark.skipif(not _is_index_available(), reason="ChromaDB index not available")
@pytest.mark.parametrize("case", _load_cases(), ids=[c["id"] for c in _load_cases()])
def test_regression_case(case, collection):
    from advisor import build_advice
    from searcher import search

    question = case["question"]
    expected_authority = case["expected_authority_level"]
    expected_qtype = case["expected_question_type"]
    expected_path_contains = case.get("expected_basis_path_contains")

    results = search(collection, question)
    advice = build_advice(question, results)

    assert advice["authority_level"] == expected_authority, (
        f"[{case['id']}] authority_level mismatch: "
        f"got {advice['authority_level']!r}, expected {expected_authority!r}"
    )

    assert advice["question_type"] == expected_qtype, (
        f"[{case['id']}] question_type mismatch: "
        f"got {advice['question_type']!r}, expected {expected_qtype!r}"
    )

    if expected_path_contains is not None:
        assert advice["basis"], f"[{case['id']}] expected basis entries but got none"
        basis_path = advice["basis"][0]["path"]
        assert expected_path_contains in basis_path, (
            f"[{case['id']}] basis path mismatch: "
            f"got {basis_path!r}, expected to contain {expected_path_contains!r}"
        )
    # expected_basis_path_contains: null → path 검증 생략 (basis 유무 무관)
