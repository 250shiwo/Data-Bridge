"""MCP 工具层测试：注册、脱敏、错误转换、护栏与同步路径（全部进程内调用）。"""
import asyncio
import json

import pytest

from databridge.mcp.server import create_mcp
from databridge.storage.connections import ConnectionInfo, ConnectionStore
from tests.conftest import FakeConnection


def _tool_names(mcp):
    return {t.name for t in asyncio.run(mcp.list_tools())}


def _contents(mcp, name, args=None):
    """进程内调用工具，返回原始 content 块列表（兼容 SDK 是否附带结构化结果）。"""
    res = asyncio.run(mcp.call_tool(name, args or {}))
    return res[0] if isinstance(res, tuple) else res


def _call(mcp, name, args=None):
    """调用工具并解析每个 content 块（JSON 优先，纯文本回退），返回解析结果列表。"""
    out = []
    for c in _contents(mcp, name, args):
        try:
            out.append(json.loads(c.text))
        except ValueError:
            out.append(c.text)
    return out


@pytest.fixture
def data_dir(tmp_path):
    """预置 dev（普通）与 prod（受保护）两条连接，密码 pw! 用于脱敏断言。"""
    store = ConnectionStore(tmp_path)
    store.save(ConnectionInfo(alias="dev", host="h", port=3306, user="u",
                              password="pw!", default_db=None, protected=False))
    store.save(ConnectionInfo(alias="prod", host="h", port=3306, user="u",
                              password="pw!", default_db=None, protected=True))
    return tmp_path


def test_list_connections_registered(data_dir):
    m = create_mcp(data_dir=data_dir)
    assert "list_connections" in _tool_names(m)


def test_list_connections_no_password(data_dir):
    m = create_mcp(data_dir=data_dir)
    items = _call(m, "list_connections")
    assert {i["alias"] for i in items} == {"dev", "prod"}
    prod = [i for i in items if i["alias"] == "prod"][0]
    assert prod["protected"] is True
    raw = "".join(c.text for c in _contents(m, "list_connections"))
    assert "pw!" not in raw
