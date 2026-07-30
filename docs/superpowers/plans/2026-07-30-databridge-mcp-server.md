# DataBridge MCP stdio server 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DataBridge 增加 MCP stdio server 面孔，暴露 5 个工具（list_connections / list_databases / list_tables / preview_sync / execute_sync）供 MySmallAgent 子进程拉起调用。

**Architecture:** 新增 `databridge/mcp/server.py` 薄壳层（与 `databridge/web/app.py` 完全同构），`create_mcp(data_dir, connect)` 工厂内构建 `ConnectionStore + SyncService`，工具函数 1-3 行转发；根目录 `mcp_server.py` 为 3 行启动壳。护栏全部复用 service 层，engine / service / storage / web 零改动。

**Tech Stack:** Python 3.11+、uv、官方 `mcp` SDK（FastMCP）、pytest（进程内调用，不起 stdio 进程、不连真实 MySQL）。

**Spec:** `docs/superpowers/specs/2026-07-30-databridge-mcp-server-design.md`

## Global Constraints

- 传输方式 stdio、入口文件 `mcp_server.py`、FastMCP SDK：需求 §2 契约锁定，不可变。
- server 名称固定 `"mysql-sync"`（agent 侧注册为 `mcp_mysql-sync_{工具名}`）。
- 依赖新增 `mcp>=1.0`，用 `uv add` 管理。
- 工具参数一律扁平化；参数与返回值只出现连接别名，永不出现密码。
- 业务错误 → `[错误码] 中文提示`；未知异常 → `服务内部错误：{异常类名}`，不回显原文。
- stdio 纪律：MCP 层禁止任何 `print`，stdout 是 JSON-RPC 信道。
- MCP 层不重复实现护栏，受保护判定完全走 `SyncService._guard_write`。
- 代码注释/docstring 全中文；docstring 会原样展示给 LLM，是护栏的一部分。
- 每个任务收尾运行 `uv run pytest -q` 保证全量绿。

---

### Task 1: MCP 薄壳骨架（依赖、create_mcp、_safe、list_connections）

**Files:**
- Modify: `pyproject.toml`（`uv add` 自动完成）
- Create: `databridge/mcp/__init__.py`（空文件，与 `databridge/web/__init__.py` 一致）
- Create: `databridge/mcp/server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `ConnectionStore(data_dir)`、`SyncService(store, connect=...)`、`store.list_safe()`（均为现有代码）。
- Produces: `create_mcp(data_dir: Path | None = None, connect=open_connection) -> FastMCP`；装饰器 `_safe(fn)`；测试助手 `_tool_names(mcp)`、`_contents(mcp, name, args)`、`_call(mcp, name, args)` 与夹具 `data_dir`（后续任务全部复用）。

- [ ] **Step 1: 安装依赖**

```powershell
uv add "mcp>=1.0"
```

预期：`pyproject.toml` 的 dependencies 出现 `mcp>=1.0`，`uv.lock` 更新，无报错。

说明：`databridge/mcp` 包名与 SDK 顶级包 `mcp` 不冲突——Python 3 绝对导入下 `from mcp.server.fastmcp import ...` 只会解析到 site-packages 的 SDK 包。

- [ ] **Step 2: 创建空的包初始化文件**

创建 `databridge/mcp/__init__.py`，内容为空（0 字节，与 `databridge/web/__init__.py` 相同）。

- [ ] **Step 3: 写失败测试**

创建 `tests/test_mcp_server.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认失败**

```powershell
uv run pytest tests/test_mcp_server.py -v
```

预期：收集阶段即 FAIL —— `ModuleNotFoundError: No module named 'databridge.mcp.server'`。

- [ ] **Step 5: 最小实现**

创建 `databridge/mcp/server.py`：

```python
"""MCP 薄壳层：FastMCP 工具定义，业务全部委托 SyncService。

stdio 纪律：本层禁止 print，stdout 是 JSON-RPC 信道；日志走 stderr（FastMCP 默认）。
"""
from functools import wraps
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from databridge.engine.connection import open_connection
from databridge.errors import DataBridgeError
from databridge.service import SyncService
from databridge.storage.connections import ConnectionStore


def _safe(fn):
    """业务错误转 [错误码] 中文提示；未知异常只回类名，避免凭据进入对话上下文。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DataBridgeError as exc:
            raise RuntimeError(f"[{exc.code}] {exc.message}") from None
        except Exception as exc:
            raise RuntimeError(f"服务内部错误：{type(exc).__name__}") from None
    return wrapper


def create_mcp(data_dir: Path | None = None, connect=open_connection) -> FastMCP:
    """创建 MCP server；data_dir / connect 可注入以便测试。"""
    store = ConnectionStore(data_dir or Path("data"))
    svc = SyncService(store, connect=connect)
    mcp = FastMCP("mysql-sync")

    @mcp.tool()
    @_safe
    def list_connections() -> list[dict]:
        """列出已配置的 MySQL 连接别名及基本信息（不含任何凭据）。

        其他工具的 alias 参数必须取自本工具返回的 alias 字段；
        protected=true 表示受保护连接（如生产库），写入需要额外确认。
        """
        return store.list_safe()

    return mcp
```

注意：`svc` 本任务暂未使用（Task 2 起使用），若 lint 抱怨可忽略——不要删除。

- [ ] **Step 6: 运行测试确认通过**

```powershell
uv run pytest tests/test_mcp_server.py -v
```

预期：2 passed。

- [ ] **Step 7: 全量回归 + 提交**

```powershell
uv run pytest -q
git add pyproject.toml uv.lock databridge/mcp/ tests/test_mcp_server.py
git commit -m "feat: MCP 薄壳骨架与 list_connections 工具"
```

预期：全量测试通过，提交成功。

---

### Task 2: 元数据工具与错误转换（list_databases、list_tables、_safe 行为验证）

**Files:**
- Modify: `databridge/mcp/server.py`（`create_mcp` 内追加两个工具）
- Test: `tests/test_mcp_server.py`（文件末尾追加）

**Interfaces:**
- Consumes: Task 1 的 `create_mcp(data_dir, connect)`、`_call` / `data_dir` 测试助手；现有 `svc.list_databases(alias)` / `svc.list_tables(alias, db)`。
- Produces: MCP 工具 `list_databases(alias: str) -> list[str]`、`list_tables(alias: str, db: str) -> list[str]`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_mcp_server.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
uv run pytest tests/test_mcp_server.py -v
```

预期：新增 3 个用例 FAIL（工具 `list_databases` 不存在，FastMCP 抛 Unknown tool / ToolError）；Task 1 的 2 个用例保持 PASS。

- [ ] **Step 3: 最小实现**

在 `databridge/mcp/server.py` 的 `create_mcp` 内、`return mcp` 之前追加：

```python
    @mcp.tool()
    @_safe
    def list_databases(alias: str) -> list[str]:
        """列出指定连接（alias）上的全部数据库名。alias 必须来自 list_connections。"""
        return svc.list_databases(alias)

    @mcp.tool()
    @_safe
    def list_tables(alias: str, db: str) -> list[str]:
        """列出指定连接（alias）指定库（db）下的全部表名。"""
        return svc.list_tables(alias, db)
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
uv run pytest tests/test_mcp_server.py -v
```

预期：5 passed。

- [ ] **Step 5: 全量回归 + 提交**

```powershell
uv run pytest -q
git add databridge/mcp/server.py tests/test_mcp_server.py
git commit -m "feat: MCP 元数据工具与统一错误转换"
```

---

### Task 3: 同步工具与护栏（preview_sync、execute_sync）

**Files:**
- Modify: `databridge/mcp/server.py`（`create_mcp` 内追加两个工具）
- Test: `tests/test_mcp_server.py`（文件末尾追加）

**Interfaces:**
- Consumes: Task 1 的 `create_mcp` / `_call` / `data_dir`；现有 `svc.preview_sync(src, dst, where)`、`svc.execute_sync(src, dst, where, confirm)`（src/dst 为 `{"alias", "db", "table"}` 字典）。
- Produces: MCP 工具 `preview_sync(src_alias, src_db, src_table, dst_alias, dst_db, dst_table, where=None) -> dict`、`execute_sync(同上 + confirm=False) -> dict`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_mcp_server.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
uv run pytest tests/test_mcp_server.py -v
```

预期：新增 3 个用例 FAIL（Unknown tool），已有 5 个保持 PASS。

- [ ] **Step 3: 最小实现**

在 `databridge/mcp/server.py` 的 `create_mcp` 内、`return mcp` 之前追加：

```python
    @mcp.tool()
    @_safe
    def preview_sync(src_alias: str, src_db: str, src_table: str,
                     dst_alias: str, dst_db: str, dst_table: str,
                     where: str | None = None) -> dict:
        """dry-run 比对源表与目标表的差异，不写任何数据。

        返回 to_insert（目标缺失行数）、to_update（内容不同行数）、
        sample_pks（差异行主键示例，最多 10 个）。
        执行 execute_sync 前必须先调用本工具，并把结果汇报给用户确认。
        where 为可选的源表过滤 SQL 条件（如 "id > 100"），只作用于源表读取。
        """
        return svc.preview_sync(
            {"alias": src_alias, "db": src_db, "table": src_table},
            {"alias": dst_alias, "db": dst_db, "table": dst_table}, where)

    @mcp.tool()
    @_safe
    def execute_sync(src_alias: str, src_db: str, src_table: str,
                     dst_alias: str, dst_db: str, dst_table: str,
                     where: str | None = None, confirm: bool = False) -> dict:
        """真正执行增量同步：新增 + 同主键 upsert 覆盖，绝不删除目标行。

        调用前必须先用 preview_sync 预览差异并经用户确认。
        目标为受保护连接（list_connections 中 protected=true）时必须
        显式传 confirm=true，否则拒绝执行。
        返回 inserted / updated 行数统计。
        """
        return svc.execute_sync(
            {"alias": src_alias, "db": src_db, "table": src_table},
            {"alias": dst_alias, "db": dst_db, "table": dst_table},
            where, confirm)
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
uv run pytest tests/test_mcp_server.py -v
```

预期：8 passed。

- [ ] **Step 5: 全量回归 + 提交**

```powershell
uv run pytest -q
git add databridge/mcp/server.py tests/test_mcp_server.py
git commit -m "feat: MCP 同步工具 preview/execute 与受保护护栏"
```

---

### Task 4: stdio 入口、注册完整性与接入文档

**Files:**
- Create: `mcp_server.py`（项目根目录，需求 §2 契约固定路径）
- Modify: `README.md`（追加 MCP 接入章节）
- Test: `tests/test_mcp_server.py`（文件末尾追加）

**Interfaces:**
- Consumes: Task 1-3 的 `create_mcp` 与 5 个已注册工具、`_tool_names` 测试助手。
- Produces: 可被 `uv --directory <项目> run python mcp_server.py` 拉起的 stdio 入口。

- [ ] **Step 1: 写失败测试（注册完整性）**

在 `tests/test_mcp_server.py` 末尾追加：

```python
def test_all_five_tools_registered(data_dir):
    m = create_mcp(data_dir=data_dir)
    assert _tool_names(m) == {"list_connections", "list_databases", "list_tables",
                              "preview_sync", "execute_sync"}
```

- [ ] **Step 2: 运行测试确认当前状态**

```powershell
uv run pytest tests/test_mcp_server.py -v
```

预期：Task 1-3 完成后此用例应直接 PASS（9 passed）。若 FAIL，说明工具名或数量与设计不符，须先修正 server.py 而不是改测试。

- [ ] **Step 3: 创建 stdio 入口**

创建根目录 `mcp_server.py`：

```python
"""MCP stdio 入口：agent 以子进程拉起（uv --directory <项目> run python mcp_server.py）。"""
from databridge.mcp.server import create_mcp

if __name__ == "__main__":
    create_mcp().run()  # FastMCP 默认 stdio 传输
```

- [ ] **Step 4: 验证入口可导入（不阻塞）**

```powershell
uv run python -c "import mcp_server; print('entry ok')"
```

预期：输出 `entry ok` 且立即退出（`__main__` 保护生效，不会挂起等待 stdio）。

- [ ] **Step 5: README 追加 MCP 接入章节**

在 `README.md` 末尾追加：

```markdown
## MCP 接入（stdio）

本项目同时是一个 MCP stdio server，暴露 5 个工具：
`list_connections`、`list_databases`、`list_tables`、`preview_sync`、`execute_sync`。

agent 侧 `mcp.json` 配置示例（`<本项目绝对路径>` 替换为实际路径）：

​```json
{
  "mcpServers": {
    "mysql-sync": {
      "command": "uv",
      "args": ["--directory", "<本项目绝对路径>", "run", "python", "mcp_server.py"]
    }
  }
}
​```

说明：

- 连接只能在 Web GUI 中添加/编辑，MCP 工具一律按别名引用，凭据永不出现在参数或返回值中；
- 向受保护连接写入时 `execute_sync` 必须显式携带 `confirm=true`，否则拒绝；
- 推荐流程：先 `preview_sync` 预览差异并向用户汇报，确认后再 `execute_sync`。
```

（注意：写入 README 时去掉上面代码块内 ​``` 前的零宽转义，保证是合法的嵌套代码块。）

- [ ] **Step 6: 全量回归 + 提交**

```powershell
uv run pytest -q
git add mcp_server.py README.md tests/test_mcp_server.py
git commit -m "feat: MCP stdio 入口与接入文档"
```

预期：全量测试通过（9 个 MCP 用例 + 既有用例全绿）。

- [ ] **Step 7: 人工冒烟（不写自动化）**

把 README 中的 `mcp.json` 片段配入任一 MCP client（如本机 IDE 的 MCP 配置），确认工具列表出现上述 5 个工具、`list_connections` 返回内容不含密码。完成后向需求方汇报结果。
