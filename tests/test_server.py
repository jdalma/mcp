from __future__ import annotations

from vault_decision import server


def test_resolve_vault_file_allows_inside_path(tmp_path):
    target = tmp_path / "01 Notes" / "Decision - X.md"
    target.parent.mkdir()
    target.write_text("body", encoding="utf-8")

    assert server._resolve_vault_file(tmp_path, "01 Notes/Decision - X.md") == target


def test_resolve_vault_file_blocks_parent_escape(tmp_path):
    assert server._resolve_vault_file(tmp_path, "../outside.md") is None


def test_read_decision_blocks_path_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: object())
    monkeypatch.setattr(server, "get_vault_path", lambda: tmp_path)

    assert server.read_decision("../outside.md") == "Invalid file path: ../outside.md"


def test_read_decision_rejects_directory(tmp_path, monkeypatch):
    (tmp_path / "01 Notes").mkdir()
    monkeypatch.setattr(server, "_get_conn", lambda: object())
    monkeypatch.setattr(server, "get_vault_path", lambda: tmp_path)

    assert server.read_decision("01 Notes") == "Invalid file path: 01 Notes"


def test_read_decision_reads_inside_file(tmp_path, monkeypatch):
    target = tmp_path / "Decision - X.md"
    target.write_text("decision body", encoding="utf-8")
    monkeypatch.setattr(server, "_get_conn", lambda: object())
    monkeypatch.setattr(server, "get_vault_path", lambda: tmp_path)

    assert server.read_decision("Decision - X.md") == "decision body"
