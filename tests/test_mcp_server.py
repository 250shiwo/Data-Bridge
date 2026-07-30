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


def test_list_databases_and_tables(data_dir):
    # inspector.list_databases 取每行首个值；list_tables 取 name 字段
    conns = [
        FakeConnection(results=[[{"Database": "shop"}, {"Database": "logs"}]]),
        FakeConnection(results=[[{"name": "orders"}, {"name": "users"}]]),
    ]
    m = create_mcp(data_dir=data_dir, connect=lambda info, db=None: conns.pop(0))
    assert _call(m, "list_databases", {"alias": "dev"}) == ["shop", "logs"]
    assert _call(m, "list_tables", {"alias": "dev", "db": "shop"}) == ["orders", "users"]


def test_unknown_alias_returns_business_error(data_dir):
    m = create_mcp(data_dir=data_dir, connect=lambda info, db=None: FakeConnection())
    with pytest.raises(Exception) as ei:
        _call(m, "list_databases", {"alias": "nope"})
    assert "[connection_not_found]" in str(ei.value)
    assert "不存在" in str(ei.value)


def test_unknown_exception_masked(data_dir):
    def boom(info, db=None):
        raise RuntimeError("password=pw! leaked")
    m = create_mcp(data_dir=data_dir, connect=boom)
    with pytest.raises(Exception) as ei:
        _call(m, "list_databases", {"alias": "dev"})
    assert "服务内部错误：RuntimeError" in str(ei.value)
    assert "pw!" not in str(ei.value)


COL_META = [
    {"name": "id", "type": "int", "is_pk": 1, "is_autoinc": 1},
    {"name": "a", "type": "int", "is_pk": 0, "is_autoinc": 0},
]

SYNC_ARGS = {"src_alias": "dev", "src_db": "s", "src_table": "t",
             "dst_alias": "prod", "dst_db": "d", "dst_table": "t"}


def _sync_conns():
    """源/目标 fake 连接。源按序弹出：get_columns、第 1 批 1 行、空批终止；
    目标按序弹出：get_columns、按主键查现有行（空 → 差异为 1 行新增）。"""
    return [
        FakeConnection(results=[COL_META, [{"id": 1, "a": 10}], []]),  # 源
        FakeConnection(results=[COL_META, []]),                        # 目标
    ]


def test_execute_sync_protected_rejected(data_dir):
    m = create_mcp(data_dir=data_dir, connect=lambda info, db=None: FakeConnection())
    with pytest.raises(Exception) as ei:
        _call(m, "execute_sync", SYNC_ARGS)   # confirm 缺省 False
    assert "[protected_connection]" in str(ei.value)
    assert "受保护" in str(ei.value)


def test_execute_sync_protected_confirmed(data_dir):
    conns = _sync_conns()
    m = create_mcp(data_dir=data_dir, connect=lambda info, db=None: conns.pop(0))
    out = _call(m, "execute_sync", dict(SYNC_ARGS, confirm=True))
    assert out == [{"inserted": 1, "updated": 0}]


def test_preview_sync_reports_diff_without_confirm(data_dir):
    conns = _sync_conns()
    m = create_mcp(data_dir=data_dir, connect=lambda info, db=None: conns.pop(0))
    out = _call(m, "preview_sync", SYNC_ARGS)   # 目标受保护，但读操作不需要 confirm
    assert out == [{"to_insert": 1, "to_update": 0, "sample_pks": [[1]]}]


def test_all_tools_registered(data_dir):
    m = create_mcp(data_dir=data_dir)
    assert _tool_names(m) == {"list_connections", "list_databases", "list_tables",
                              "preview_sync", "execute_sync", "browse_table"}


# get_columns 会把原始行的 is_pk/is_autoinc 转成 bool
EXPECTED_COLS = [
    {"name": "id", "type": "int", "is_pk": True, "is_autoinc": True},
    {"name": "a", "type": "int", "is_pk": False, "is_autoinc": False},
]


def _browse_conn(rows, total):
    # 单连接按序弹出：get_columns、count、数据行
    return FakeConnection(results=[COL_META, [{"total": total}], rows])


def test_browse_table_passthrough(data_dir):
    rows = [{"id": 1, "a": 10}, {"id": 2, "a": 20}]
    conn = _browse_conn(rows, 2)
    m = create_mcp(data_dir=data_dir, connect=lambda info, db=None: conn)
    out = _call(m, "browse_table", {"alias": "dev", "db": "s", "table": "t"})
    assert out == [{"columns": EXPECTED_COLS, "rows": rows, "total": 2}]


def test_browse_table_page_size_cap(data_dir):
    m = create_mcp(data_dir=data_dir, connect=lambda info, db=None: FakeConnection())
    with pytest.raises(Exception) as ei:
        _call(m, "browse_table",
              {"alias": "dev", "db": "s", "table": "t", "page_size": 500})
    assert "[invalid_query]" in str(ei.value)
    assert "200" in str(ei.value)


def test_browse_table_forwards_filters(data_dir):
    conn = _browse_conn([{"id": 1, "a": 10}], 1)
    m = create_mcp(data_dir=data_dir, connect=lambda info, db=None: conn)
    out = _call(m, "browse_table", {
        "alias": "dev", "db": "s", "table": "t",
        "filters": [{"column": "a", "op": "gte", "value": 5}]})
    assert out == [{"columns": EXPECTED_COLS, "rows": [{"id": 1, "a": 10}], "total": 1}]
    used = [p for _, params in conn.cursor_obj.executed for p in (params or [])]
    assert 5 in used
