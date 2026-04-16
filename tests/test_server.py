# tests/test_server.py
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
    assert "list_decisions" in tool_names
    assert "read_decision" in tool_names
    assert "reindex" in tool_names
