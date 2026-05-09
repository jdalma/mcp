# tests/test_server.py
import asyncio
import importlib


def test_server_module_imports():
    """server.py가 에러 없이 import 가능한지 확인."""
    import server
    assert hasattr(server, "mcp")
    assert hasattr(server, "main")
    assert hasattr(server, "_ensure_initialized")


def test_mcp_tools_registered():
    """MCP tool이 올바르게 등록되어 있는지 확인."""
    import server
    tool_names = [t.name for t in server.mcp._tool_manager.list_tools()]
    assert "query" in tool_names
    assert "advise" in tool_names
    assert "list_decisions" in tool_names
    assert "read_decision" in tool_names
    assert "reindex" in tool_names


def test_read_decision_rejects_path_escape(tmp_path, monkeypatch):
    import server

    vault = tmp_path / "vault"
    notes = vault / "01 Notes"
    notes.mkdir(parents=True)
    (notes / "Decision - Safe.md").write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    monkeypatch.setattr(server, "get_vault_path", lambda: vault)

    result = asyncio.run(server.read_decision(str(outside)))

    assert result == f"File not found: {outside}"


def test_read_decision_rejects_inbox_files(tmp_path, monkeypatch):
    import server

    vault = tmp_path / "vault"
    inbox = vault / "00 Inbox"
    inbox.mkdir(parents=True)
    (inbox / "Raw.md").write_text("raw", encoding="utf-8")

    monkeypatch.setattr(server, "get_vault_path", lambda: vault)

    result = asyncio.run(server.read_decision("00 Inbox/Raw.md"))

    assert result == "File not found: 00 Inbox/Raw.md"


def test_read_decision_rejects_dotdot_escape(tmp_path, monkeypatch):
    import server

    vault = tmp_path / "vault"
    (vault / "01 Notes").mkdir(parents=True)

    monkeypatch.setattr(server, "get_vault_path", lambda: vault)

    result = asyncio.run(server.read_decision("../../../etc/passwd"))

    assert "File not found" in result


def test_read_decision_rejects_outside_symlink(tmp_path, monkeypatch):
    import server

    vault = tmp_path / "vault"
    notes = vault / "01 Notes"
    notes.mkdir(parents=True)

    outside = tmp_path / "secret.md"
    outside.write_text("secret content", encoding="utf-8")

    symlink = notes / "evil-link.md"
    symlink.symlink_to(outside)

    monkeypatch.setattr(server, "get_vault_path", lambda: vault)

    result = asyncio.run(server.read_decision("01 Notes/evil-link.md"))

    assert result != "secret content"


def test_read_decision_rejects_absolute_path_injection(tmp_path, monkeypatch):
    import server

    vault = tmp_path / "vault"
    (vault / "01 Notes").mkdir(parents=True)

    monkeypatch.setattr(server, "get_vault_path", lambda: vault)

    result = asyncio.run(server.read_decision("/etc/passwd"))

    assert "File not found" in result
