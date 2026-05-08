"""Tests for swap protocol (_swap_collection)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import chromadb
import pytest

SAMPLE_DECISION = """---
type: decision
status: decided
---

# Decision: Swap Test

## Decision

Option A를 선택한다.
"""


def _make_collection(client, name: str):
    return client.get_or_create_collection(name=name)


@pytest.fixture()
def in_memory_env(tmp_path, monkeypatch):
    """in-memory chromadb + tmp vault + server globals 초기화."""
    import server
    import config

    notes = tmp_path / "01 Notes"
    notes.mkdir()
    (notes / "Decision - A.md").write_text(SAMPLE_DECISION)

    client = chromadb.Client()
    col = _make_collection(client, "vault_decisions")

    monkeypatch.setattr(server, "_collection", col)
    monkeypatch.setattr(server, "_previous_collection_name", None, raising=False)
    monkeypatch.setattr(server, "_chroma_client", client, raising=False)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    return {"client": client, "collection": col, "vault": tmp_path}


def test_swap_success_replaces_collection(in_memory_env, monkeypatch):
    """swap 성공 시 _collection 핸들이 새 collection으로 교체된다."""
    import server

    old_name = in_memory_env["collection"].name

    async def run():
        await server._swap_collection(validate=lambda col: True)

    asyncio.run(run())

    assert server._collection.name != old_name, (
        f"swap 후 _collection이 교체되지 않음: 여전히 {server._collection.name!r}"
    )


def test_swap_rollback_on_validation_fail(in_memory_env, monkeypatch):
    """검증 실패 시 _collection은 옛 핸들을 유지하고 신규 collection은 삭제된다."""
    import server

    client = in_memory_env["client"]
    old_col = in_memory_env["collection"]
    old_name = old_col.name

    created_names: list[str] = []
    original_get_or_create = client.get_or_create_collection

    def tracking_get_or_create(name, **kwargs):
        col = original_get_or_create(name, **kwargs)
        if name != old_name:
            created_names.append(name)
        return col

    monkeypatch.setattr(client, "get_or_create_collection", tracking_get_or_create)

    async def run():
        await server._swap_collection(validate=lambda col: False)

    asyncio.run(run())

    # 핸들이 원래대로
    assert server._collection.name == old_name, (
        f"롤백 후 _collection 핸들이 변경됨: {server._collection.name!r}"
    )

    # swap 중 생성된 신규 collection이 삭제됐는지 확인
    existing_names = {c.name for c in client.list_collections()}
    leaked = [n for n in created_names if n in existing_names]
    assert not leaked, (
        f"롤백 후 신규 collection이 남아 있음: {leaked}"
    )


def test_swap_concurrent_request_safety(in_memory_env, monkeypatch):
    """swap 중 옛 핸들을 잡고 있던 참조는 swap 완료 후에도 정상 쿼리 가능하다."""
    import server

    # swap 전에 옛 핸들 참조 캡처 (advise 진행 중인 요청 시뮬레이션)
    old_ref = server._collection

    async def run():
        await server._swap_collection(validate=lambda col: True)

    asyncio.run(run())

    # 새 핸들로 교체됐는지 확인
    assert server._collection.name != old_ref.name

    # 옛 핸들은 여전히 조회 가능 (2-generation 방식: 즉시 삭제 안 됨)
    try:
        old_ref.count()  # 삭제됐다면 예외 발생
    except Exception as e:
        pytest.fail(f"옛 핸들이 swap 직후 삭제됨 — concurrent request 안전성 위반: {e}")
