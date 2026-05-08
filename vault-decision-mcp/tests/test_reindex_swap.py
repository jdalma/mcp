"""Tests for reindex(force=True) using swap protocol."""

from __future__ import annotations

import asyncio

import chromadb
import pytest

SAMPLE_DECISION = """---
type: decision
status: decided
---

# Decision: Reindex Swap Test

## Decision

Option B를 선택한다.
"""


@pytest.fixture()
def in_memory_env(tmp_path, monkeypatch):
    """in-memory chromadb + tmp vault + server globals 초기화."""
    import server
    import config

    notes = tmp_path / "01 Notes"
    notes.mkdir()
    (notes / "Decision - B.md").write_text(SAMPLE_DECISION)

    client = chromadb.Client()
    col = client.get_or_create_collection(name="vault_decisions")

    monkeypatch.setattr(server, "_collection", col)
    monkeypatch.setattr(server, "_previous_collection_name", None, raising=False)
    monkeypatch.setattr(server, "_chroma_client", client, raising=False)
    monkeypatch.setattr(config, "get_vault_path", lambda: tmp_path)

    return {"client": client, "collection": col, "vault": tmp_path}


def test_reindex_force_uses_swap_protocol(in_memory_env, monkeypatch):
    """reindex(force=True)는 _swap_collection을 호출해 새 collection으로 교체한다."""
    import server

    old_name = in_memory_env["collection"].name
    swap_called = []

    original_swap = server._swap_collection

    async def spy_swap(**kwargs):
        swap_called.append(kwargs)
        await original_swap(**kwargs)

    monkeypatch.setattr(server, "_swap_collection", spy_swap)

    async def run():
        return await server.reindex(force=True)

    result = asyncio.run(run())

    assert swap_called, "force=True 시 _swap_collection이 호출되지 않음"
    assert server._collection.name != old_name, (
        f"swap 후 _collection이 교체되지 않음: 여전히 {server._collection.name!r}"
    )
    assert "Reindex complete" in result


def test_reindex_incremental_does_not_use_swap(in_memory_env, monkeypatch):
    """reindex(force=False)는 _swap_collection을 호출하지 않고 증분 업데이트한다."""
    import server

    swap_called = []

    async def spy_swap(**kwargs):
        swap_called.append(kwargs)

    monkeypatch.setattr(server, "_swap_collection", spy_swap)

    async def run():
        return await server.reindex(force=False)

    result = asyncio.run(run())

    assert not swap_called, "force=False 시 _swap_collection이 호출됨 — 증분 경로를 타야 함"
    assert "Reindex complete" in result
