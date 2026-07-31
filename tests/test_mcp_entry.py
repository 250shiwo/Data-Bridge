"""入口传输选择测试：默认 stdio、环境变量切 HTTP，均为进程内验证不起真实服务。"""
import asyncio

import mcp_server


def _tool_names(mcp):
    return {t.name for t in asyncio.run(mcp.list_tools())}


def test_build_defaults_to_stdio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # 隔离 data 目录，避免污染项目根
    mcp, transport = mcp_server.build({})
    assert transport == "stdio"


def test_build_http_applies_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mcp, transport = mcp_server.build(
        {"MCP_TRANSPORT": "streamable-http", "MCP_PORT": "9000"})
    assert transport == "streamable-http"
    assert mcp.settings.host == "0.0.0.0"
    assert mcp.settings.port == 9000
    assert mcp.settings.stateless_http is True
    assert mcp.settings.json_response is True


def test_build_registers_all_six_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mcp, _ = mcp_server.build({})
    assert _tool_names(mcp) == {"list_connections", "list_databases", "list_tables",
                                "browse_table", "preview_sync", "execute_sync"}
