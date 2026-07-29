# DataBridge Web GUI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 MySQL 数据同步工具的 Web GUI：连接管理、数据浏览器勾选行同步（新增/替换）、整表增量同步。

**Architecture:** 三层解耦——engine（纯同步逻辑，无 Web 依赖）/ storage（连接配置 Fernet 加密持久化）/ web（FastAPI 薄壳 + 原生 JS + Tabulator 前端）。所有护栏在 engine/service 层实现，未来 MCP 入口直接复用 service。

**Tech Stack:** Python 3.11+ / uv / FastAPI + Uvicorn / pymysql / cryptography(Fernet) / Tabulator 5.x（本地 vendor）/ pytest

**Spec:** `docs/superpowers/specs/2026-07-29-databridge-web-sync-design.md`

## Global Constraints

- Python `>=3.11`，包管理用 `uv`，所有命令通过 `uv run` 执行；
- 代码注释、错误提示一律**中文**；
- 任何 API 返回值、日志、异常信息**不得包含密码**；
- `data/` 目录（连接配置+密钥）必须在 `.gitignore` 中；
- 写操作目标为受保护连接时必须显式 `confirm=true`，否则拒绝（HTTP 403）；
- 前端静态资源本地 vendor，不依赖 CDN；
- SQL 一律参数化；库名/表名/列名经白名单或标识符校验后才可拼入 SQL；
- 每个任务完成即 `git commit`。

---

### Task 1: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `databridge/__init__.py`、`databridge/engine/__init__.py`、`databridge/storage/__init__.py`、`databridge/web/__init__.py`
- Test: `tests/__init__.py`、`tests/test_smoke.py`

**Interfaces:**
- Consumes: 无
- Produces: 可 `uv run pytest` 的项目骨架；包名 `databridge`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "databridge"
version = "0.1.0"
description = "MySQL 表数据同步工具（Web GUI + 未来 MCP）"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "pymysql>=1.1",
    "cryptography>=42.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["databridge"]
```

- [ ] **Step 2: 写 .gitignore**

```gitignore
# 本地凭据与密钥，绝不进 git
data/

# Python
__pycache__/
*.pyc
.venv/
.pytest_cache/
*.egg-info/
```

- [ ] **Step 3: 创建包结构与冒烟测试**

创建空文件 `databridge/__init__.py`、`databridge/engine/__init__.py`、`databridge/storage/__init__.py`、`databridge/web/__init__.py`、`tests/__init__.py`。

`tests/test_smoke.py`:

```python
"""冒烟测试：确认包可导入。"""
import databridge


def test_import():
    assert databridge is not None
```

- [ ] **Step 4: 安装依赖并跑测试**

Run: `uv sync`（生成 `.venv` 与 `uv.lock`）
Run: `uv run pytest -v`
Expected: `test_import PASSED`，1 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore databridge tests uv.lock
git commit -m "chore: 项目脚手架（uv + pytest + 包结构）"
```

---

### Task 2: 错误体系与连接配置存储

**Files:**
- Create: `databridge/errors.py`
- Create: `databridge/storage/connections.py`
- Test: `tests/test_storage_connections.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `databridge.errors`：`DataBridgeError(message)` 基类（属性 `code: str`、`http_status: int`、`message: str`），子类 `ConnectionNotFoundError`、`ProtectedConnectionError(http_status=403)`、`TableNotFoundError`、`NoPrimaryKeyError`、`ColumnMismatchError`、`PrimaryKeyMismatchError`、`SelectionCountMismatchError`、`InvalidQueryError`
  - `ConnectionInfo` dataclass：`alias, host, port, user, password, default_db(str|None), protected(bool)`
  - `ConnectionStore(data_dir: Path)`：`list_safe() -> list[dict]`（无密码）、`get(alias) -> ConnectionInfo`、`save(info)`（更新时 `password==""` 保留旧密码）、`delete(alias)`

- [ ] **Step 1: 写失败测试**

`tests/test_storage_connections.py`:

```python
"""连接配置存储测试：加密往返、无明文、空密码保留、删除。"""
import json
import pytest

from databridge.errors import ConnectionNotFoundError
from databridge.storage.connections import ConnectionInfo, ConnectionStore


def make_info(**kw) -> ConnectionInfo:
    base = dict(alias="dev", host="127.0.0.1", port=3306, user="root",
                password="s3cret!", default_db=None, protected=False)
    base.update(kw)
    return ConnectionInfo(**base)


def test_save_and_get_roundtrip(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info())
    got = store.get("dev")
    assert got.password == "s3cret!"
    assert got.host == "127.0.0.1"
    assert got.protected is False


def test_file_has_no_plaintext_password(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info())
    raw = (tmp_path / "connections.json").read_text(encoding="utf-8")
    assert "s3cret!" not in raw


def test_list_safe_excludes_password(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info(protected=True))
    items = store.list_safe()
    assert items == [{"alias": "dev", "host": "127.0.0.1", "port": 3306,
                      "user": "root", "default_db": None, "protected": True}]


def test_update_with_blank_password_keeps_old(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info())
    store.save(make_info(password="", host="10.0.0.2"))
    got = store.get("dev")
    assert got.password == "s3cret!"
    assert got.host == "10.0.0.2"


def test_get_missing_raises(tmp_path):
    store = ConnectionStore(tmp_path)
    with pytest.raises(ConnectionNotFoundError):
        store.get("nope")


def test_delete(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info())
    store.delete("dev")
    with pytest.raises(ConnectionNotFoundError):
        store.get("dev")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_storage_connections.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'databridge.errors'`

- [ ] **Step 3: 实现 errors.py 与 connections.py**

`databridge/errors.py`:

```python
"""业务可预期错误体系：携带错误码、HTTP 状态与中文提示。"""


class DataBridgeError(Exception):
    """所有业务错误的基类。"""
    code = "internal_error"
    http_status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConnectionNotFoundError(DataBridgeError):
    code = "connection_not_found"
    http_status = 404


class ProtectedConnectionError(DataBridgeError):
    code = "protected_connection"
    http_status = 403


class TableNotFoundError(DataBridgeError):
    code = "table_not_found"
    http_status = 404


class NoPrimaryKeyError(DataBridgeError):
    code = "no_primary_key"


class ColumnMismatchError(DataBridgeError):
    code = "column_mismatch"


class PrimaryKeyMismatchError(DataBridgeError):
    code = "primary_key_mismatch"


class SelectionCountMismatchError(DataBridgeError):
    code = "selection_count_mismatch"


class InvalidQueryError(DataBridgeError):
    code = "invalid_query"
```

`databridge/storage/connections.py`:

```python
"""连接配置存取：本地 JSON 持久化，密码 Fernet 加密。

密钥文件 data/.key 首次使用时自动生成；data/ 整体在 .gitignore 中。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

from databridge.errors import ConnectionNotFoundError


@dataclass
class ConnectionInfo:
    """一条 MySQL 连接配置（password 为明文，仅存在于内存）。"""
    alias: str
    host: str
    port: int
    user: str
    password: str
    default_db: str | None = None
    protected: bool = False


class ConnectionStore:
    """连接配置仓库：list_safe 永不返回密码。"""

    def __init__(self, data_dir: Path):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "connections.json"
        key_file = self._dir / ".key"
        if not key_file.exists():
            key_file.write_bytes(Fernet.generate_key())
        self._fernet = Fernet(key_file.read_bytes())

    def _load(self) -> dict:
        if not self._file.exists():
            return {}
        return json.loads(self._file.read_text(encoding="utf-8"))

    def _save_file(self, data: dict) -> None:
        self._file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_safe(self) -> list[dict]:
        """列出全部连接（不含任何密码字段）。"""
        return [
            {"alias": alias, "host": item["host"], "port": item["port"],
             "user": item["user"], "default_db": item.get("default_db"),
             "protected": item.get("protected", False)}
            for alias, item in sorted(self._load().items())
        ]

    def get(self, alias: str) -> ConnectionInfo:
        data = self._load()
        if alias not in data:
            raise ConnectionNotFoundError(f"连接 {alias} 不存在")
        item = data[alias]
        password = self._fernet.decrypt(item["password_enc"].encode()).decode()
        return ConnectionInfo(
            alias=alias, host=item["host"], port=item["port"],
            user=item["user"], password=password,
            default_db=item.get("default_db"),
            protected=item.get("protected", False))

    def save(self, info: ConnectionInfo) -> None:
        """新增或更新；更新时 password 为空字符串表示保留旧密码。"""
        data = self._load()
        if info.password == "" and info.alias in data:
            password_enc = data[info.alias]["password_enc"]
        else:
            password_enc = self._fernet.encrypt(info.password.encode()).decode()
        data[info.alias] = {
            "host": info.host, "port": info.port, "user": info.user,
            "password_enc": password_enc, "default_db": info.default_db,
            "protected": info.protected}
        self._save_file(data)

    def delete(self, alias: str) -> None:
        data = self._load()
        if alias not in data:
            raise ConnectionNotFoundError(f"连接 {alias} 不存在")
        del data[alias]
        self._save_file(data)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_storage_connections.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add databridge/errors.py databridge/storage/connections.py tests/test_storage_connections.py
git commit -m "feat: 错误体系 + 连接配置 Fernet 加密存储"
```

---

### Task 3: 测试桩（FakeConnection）与 MySQL 连接封装

**Files:**
- Create: `tests/conftest.py`
- Create: `databridge/engine/connection.py`
- Test: `tests/test_engine_connection.py`

**Interfaces:**
- Consumes: `ConnectionInfo`（Task 2）
- Produces:
  - `open_connection(info: ConnectionInfo, database: str | None = None) -> pymysql.Connection`（DictCursor、手动提交、utf8mb4）
  - `check_connection(info: ConnectionInfo) -> bool`（连通性测试）
  - 测试桩 `tests/conftest.py` 中的 `FakeCursor` / `FakeConnection`（后续引擎测试全部复用）

- [ ] **Step 1: 写测试桩 conftest.py**

`tests/conftest.py`:

```python
"""共享测试桩：模拟 pymysql 连接/游标，供引擎层单测复用。"""
from __future__ import annotations


class FakeCursor:
    """极简游标桩：按顺序弹出预置结果集，记录执行过的 SQL 与参数。"""

    def __init__(self, results: list | None = None, error: Exception | None = None):
        self.results = list(results or [])   # 每次 execute 弹出一个结果集(list[dict])
        self.error = error                   # 置为异常时，execute/executemany 抛出
        self.executed: list[tuple] = []      # [(sql, params), ...]
        self._current: list = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.error:
            raise self.error
        self._current = self.results.pop(0) if self.results else []

    def executemany(self, sql, seq_params):
        self.executed.append((sql, list(seq_params)))
        if self.error:
            raise self.error

    def fetchall(self):
        return self._current

    def fetchone(self):
        return self._current[0] if self._current else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    """极简连接桩：单游标，记录 commit/rollback 调用。"""

    def __init__(self, results: list | None = None, error: Exception | None = None):
        self.cursor_obj = FakeCursor(results, error)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True
```

- [ ] **Step 2: 写失败测试**

`tests/test_engine_connection.py`:

```python
"""连接封装测试：确认 pymysql.connect 收到正确参数。"""
from unittest.mock import patch, MagicMock

from databridge.engine.connection import open_connection, check_connection
from databridge.storage.connections import ConnectionInfo

INFO = ConnectionInfo(alias="dev", host="db.local", port=3307,
                      user="u", password="p", default_db=None, protected=False)


@patch("databridge.engine.connection.pymysql")
def test_open_connection_kwargs(mock_pymysql):
    open_connection(INFO, database="mydb")
    kwargs = mock_pymysql.connect.call_args.kwargs
    assert kwargs["host"] == "db.local"
    assert kwargs["port"] == 3307
    assert kwargs["database"] == "mydb"
    assert kwargs["autocommit"] is False
    assert kwargs["charset"] == "utf8mb4"


@patch("databridge.engine.connection.pymysql")
def test_check_connection_pings_and_closes(mock_pymysql):
    conn = MagicMock()
    mock_pymysql.connect.return_value = conn
    assert check_connection(INFO) is True
    conn.ping.assert_called_once()
    conn.close.assert_called_once()
```

- [ ] **Step 3: 运行确认失败**

Run: `uv run pytest tests/test_engine_connection.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'databridge.engine.connection'`

- [ ] **Step 4: 实现 connection.py**

`databridge/engine/connection.py`:

```python
"""MySQL 连接封装：统一 DictCursor、手动提交、utf8mb4。"""
import pymysql
import pymysql.cursors

from databridge.storage.connections import ConnectionInfo


def open_connection(info: ConnectionInfo, database: str | None = None):
    """按连接配置打开 MySQL 连接；database 为 None 时不选库。"""
    return pymysql.connect(
        host=info.host, port=info.port, user=info.user,
        password=info.password, database=database,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False, charset="utf8mb4")


def check_connection(info: ConnectionInfo) -> bool:
    """连通性测试：ping 一次即断开。失败时由调用方捕获异常。"""
    conn = open_connection(info)
    try:
        conn.ping()
        return True
    finally:
        conn.close()
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_engine_connection.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py databridge/engine/connection.py tests/test_engine_connection.py
git commit -m "feat: MySQL 连接封装 + 共享测试桩"
```

---

### Task 4: 元数据检查器 inspector

**Files:**
- Create: `databridge/engine/inspector.py`
- Test: `tests/test_engine_inspector.py`

**Interfaces:**
- Consumes: `FakeConnection`（Task 3 测试桩）、errors（Task 2）
- Produces:
  - `list_databases(conn) -> list[str]`
  - `list_tables(conn, db: str) -> list[str]`
  - `get_columns(conn, db, table) -> list[dict]`，元素 `{"name", "type", "is_pk": bool, "is_autoinc": bool}`；表不存在抛 `TableNotFoundError`
  - `get_primary_key(columns, db, table) -> list[str]`；无主键抛 `NoPrimaryKeyError`
  - `check_columns_match(src_cols, dst_cols) -> None`；列名集合（排除自增列）不一致抛 `ColumnMismatchError`，消息列出双方差异列
  - `check_pk_match(src_cols, dst_cols) -> None`；主键列名列表不一致抛 `PrimaryKeyMismatchError`
  - `ensure_identifier(name: str) -> str`；仅允许 `[0-9A-Za-z_$]+`，否则抛 `InvalidQueryError`（防注入，库/表名校验用）

- [ ] **Step 1: 写失败测试**

`tests/test_engine_inspector.py`:

```python
"""元数据检查器测试：列/主键识别、一致性校验、标识符校验。"""
import pytest

from databridge.engine import inspector
from databridge.errors import (ColumnMismatchError, InvalidQueryError,
                               NoPrimaryKeyError, PrimaryKeyMismatchError,
                               TableNotFoundError)
from tests.conftest import FakeConnection


def col(name, is_pk=False, is_autoinc=False, type_="int"):
    return {"name": name, "type": type_, "is_pk": is_pk, "is_autoinc": is_autoinc}


def test_get_columns_parses_metadata():
    conn = FakeConnection(results=[[
        {"name": "id", "type": "int", "is_pk": 1, "is_autoinc": 1},
        {"name": "title", "type": "varchar", "is_pk": 0, "is_autoinc": 0},
    ]])
    cols = inspector.get_columns(conn, "db1", "t1")
    assert cols == [col("id", True, True), col("title", type_="varchar")]


def test_get_columns_missing_table_raises():
    conn = FakeConnection(results=[[]])
    with pytest.raises(TableNotFoundError):
        inspector.get_columns(conn, "db1", "nope")


def test_get_primary_key():
    cols = [col("id", True, True), col("title", type_="varchar")]
    assert inspector.get_primary_key(cols, "db1", "t1") == ["id"]
    with pytest.raises(NoPrimaryKeyError):
        inspector.get_primary_key([col("title")], "db1", "t1")


def test_check_columns_match_ignores_autoinc():
    src = [col("id", True, True), col("a"), col("b")]
    dst = [col("nid", True, True), col("a"), col("b")]
    inspector.check_columns_match(src, dst)  # 自增主键名不同也算一致


def test_check_columns_match_reports_diff():
    src = [col("a"), col("only_src")]
    dst = [col("a"), col("only_dst")]
    with pytest.raises(ColumnMismatchError) as ei:
        inspector.check_columns_match(src, dst)
    assert "only_src" in ei.value.message
    assert "only_dst" in ei.value.message


def test_check_pk_match():
    src = [col("id", True), col("a")]
    dst = [col("code", True), col("a")]
    with pytest.raises(PrimaryKeyMismatchError):
        inspector.check_pk_match(src, dst)


def test_ensure_identifier():
    assert inspector.ensure_identifier("my_table$1") == "my_table$1"
    with pytest.raises(InvalidQueryError):
        inspector.ensure_identifier("t; DROP TABLE x")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_engine_inspector.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 inspector.py**

`databridge/engine/inspector.py`:

```python
"""元数据检查器：列结构、主键识别、一致性校验、标识符防注入。"""
import re

from databridge.errors import (ColumnMismatchError, InvalidQueryError,
                               NoPrimaryKeyError, PrimaryKeyMismatchError,
                               TableNotFoundError)

_IDENT_RE = re.compile(r"^[0-9A-Za-z_$]+$")


def ensure_identifier(name: str) -> str:
    """校验库/表/列标识符只含安全字符，否则拒绝（防 SQL 注入）。"""
    if not name or not _IDENT_RE.match(name):
        raise InvalidQueryError(f"非法标识符：{name!r}")
    return name


def list_databases(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW DATABASES")
        return [list(row.values())[0] for row in cur.fetchall()]


def list_tables(conn, db: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME", (db,))
        return [row["name"] for row in cur.fetchall()]


def get_columns(conn, db: str, table: str) -> list[dict]:
    """查询列元数据；表不存在（无任何列）时报 TableNotFoundError。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COLUMN_NAME AS name, DATA_TYPE AS type, "
            "COLUMN_KEY = 'PRI' AS is_pk, "
            "EXTRA LIKE '%%auto_increment%%' AS is_autoinc "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION", (db, table))
        rows = cur.fetchall()
    if not rows:
        raise TableNotFoundError(f"表 {db}.{table} 不存在")
    return [{"name": r["name"], "type": r["type"],
             "is_pk": bool(r["is_pk"]), "is_autoinc": bool(r["is_autoinc"])}
            for r in rows]


def get_primary_key(columns: list[dict], db: str, table: str) -> list[str]:
    pk = [c["name"] for c in columns if c["is_pk"]]
    if not pk:
        raise NoPrimaryKeyError(f"表 {db}.{table} 没有主键，无法同步")
    return pk


def check_columns_match(src_cols: list[dict], dst_cols: list[dict]) -> None:
    """校验两表列名集合完全一致（自增列除外），不一致时列出差异列。"""
    src = {c["name"] for c in src_cols if not c["is_autoinc"]}
    dst = {c["name"] for c in dst_cols if not c["is_autoinc"]}
    if src != dst:
        only_src = sorted(src - dst)
        only_dst = sorted(dst - src)
        raise ColumnMismatchError(
            f"两表列结构不一致：仅源表有 {only_src}，仅目标表有 {only_dst}")


def check_pk_match(src_cols: list[dict], dst_cols: list[dict]) -> None:
    """整表同步前置校验：主键列名列表必须一致。"""
    src_pk = [c["name"] for c in src_cols if c["is_pk"]]
    dst_pk = [c["name"] for c in dst_cols if c["is_pk"]]
    if src_pk != dst_pk:
        raise PrimaryKeyMismatchError(
            f"两表主键结构不一致：源表 {src_pk}，目标表 {dst_pk}")
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_engine_inspector.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add databridge/engine/inspector.py tests/test_engine_inspector.py
git commit -m "feat: 元数据检查器（列/主键/一致性校验/标识符防注入）"
```

---

### Task 5: 数据浏览查询 browser

**Files:**
- Create: `databridge/engine/browser.py`
- Test: `tests/test_engine_browser.py`

**Interfaces:**
- Consumes: `ensure_identifier`（Task 4）、`InvalidQueryError`（Task 2）
- Produces:
  - `build_browse_query(db, table, allowed_columns: set[str], page: int, page_size: int, filters: list[dict] | None, sort_column: str | None, sort_dir: str) -> tuple[str, list, str, list]`，返回 `(数据SQL, 数据参数, 计数SQL, 计数参数)`；filters 元素 `{"column","op","value"}`，op ∈ `eq/contains/gte/lte`
  - `browse(conn, db, table, columns: list[dict], page=1, page_size=50, filters=None, sort_column=None, sort_dir="asc") -> dict`，返回 `{"rows": list[dict], "total": int}`

- [ ] **Step 1: 写失败测试**

`tests/test_engine_browser.py`:

```python
"""数据浏览查询测试：SQL 生成、筛选/排序白名单、分页。"""
import pytest

from databridge.engine.browser import browse, build_browse_query
from databridge.errors import InvalidQueryError
from tests.conftest import FakeConnection

ALLOWED = {"id", "name"}


def test_basic_pagination_sql():
    sql, params, count_sql, count_params = build_browse_query(
        "db1", "t1", ALLOWED, page=3, page_size=50,
        filters=None, sort_column=None, sort_dir="asc")
    assert sql == "SELECT * FROM `db1`.`t1` LIMIT %s OFFSET %s"
    assert params == [50, 100]
    assert count_sql == "SELECT COUNT(*) AS total FROM `db1`.`t1`"
    assert count_params == []


def test_filters_and_sort():
    sql, params, count_sql, count_params = build_browse_query(
        "db1", "t1", ALLOWED, page=1, page_size=10,
        filters=[{"column": "name", "op": "contains", "value": "abc"},
                 {"column": "id", "op": "gte", "value": 5}],
        sort_column="id", sort_dir="desc")
    assert "WHERE `name` LIKE %s AND `id` >= %s" in sql
    assert "ORDER BY `id` DESC" in sql
    assert params == ["%abc%", 5, 10, 0]
    assert count_params == ["%abc%", 5]


def test_illegal_filter_column_rejected():
    with pytest.raises(InvalidQueryError):
        build_browse_query("db1", "t1", ALLOWED, 1, 10,
                           filters=[{"column": "pwd; --", "op": "eq", "value": 1}],
                           sort_column=None, sort_dir="asc")


def test_illegal_sort_rejected():
    with pytest.raises(InvalidQueryError):
        build_browse_query("db1", "t1", ALLOWED, 1, 10, None, "id", "evil")


def test_browse_returns_rows_and_total():
    conn = FakeConnection(results=[
        [{"total": 2}],                          # 计数查询结果
        [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],  # 数据查询结果
    ])
    cols = [{"name": "id", "type": "int", "is_pk": True, "is_autoinc": True},
            {"name": "name", "type": "varchar", "is_pk": False, "is_autoinc": False}]
    out = browse(conn, "db1", "t1", cols)
    assert out["total"] == 2
    assert len(out["rows"]) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_engine_browser.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 browser.py**

`databridge/engine/browser.py`:

```python
"""数据浏览：分页查询 + 列筛选 + 排序，全部经白名单校验。"""
from databridge.engine.inspector import ensure_identifier
from databridge.errors import InvalidQueryError

# 筛选操作符 -> SQL 片段（占位符统一 %s）
_OPS = {"eq": "= %s", "contains": "LIKE %s", "gte": ">= %s", "lte": "<= %s"}


def _build_where(filters, allowed_columns):
    clauses, params = [], []
    for f in filters or []:
        col, op, value = f.get("column"), f.get("op"), f.get("value")
        if col not in allowed_columns:
            raise InvalidQueryError(f"非法筛选列：{col!r}")
        if op not in _OPS:
            raise InvalidQueryError(f"非法筛选操作：{op!r}")
        clauses.append(f"`{col}` {_OPS[op]}")
        params.append(f"%{value}%" if op == "contains" else value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def build_browse_query(db, table, allowed_columns, page, page_size,
                       filters, sort_column, sort_dir):
    """生成 (数据SQL, 数据参数, 计数SQL, 计数参数)，列名经白名单校验。"""
    ensure_identifier(db)
    ensure_identifier(table)
    where, params = _build_where(filters, allowed_columns)
    order = ""
    if sort_column:
        if sort_column not in allowed_columns:
            raise InvalidQueryError(f"非法排序列：{sort_column!r}")
        if sort_dir not in ("asc", "desc"):
            raise InvalidQueryError(f"非法排序方向：{sort_dir!r}")
        order = f" ORDER BY `{sort_column}` {sort_dir.upper()}"
    offset = (page - 1) * page_size
    sql = f"SELECT * FROM `{db}`.`{table}`{where}{order} LIMIT %s OFFSET %s"
    count_sql = f"SELECT COUNT(*) AS total FROM `{db}`.`{table}`{where}"
    return sql, params + [page_size, offset], count_sql, list(params)


def browse(conn, db, table, columns, page=1, page_size=50,
           filters=None, sort_column=None, sort_dir="asc"):
    """执行浏览查询，返回 {"rows", "total"}。columns 来自 inspector.get_columns。"""
    allowed = {c["name"] for c in columns}
    sql, params, count_sql, count_params = build_browse_query(
        db, table, allowed, page, page_size, filters, sort_column, sort_dir)
    with conn.cursor() as cur:
        cur.execute(count_sql, count_params)
        total = cur.fetchone()["total"]
        cur.execute(sql, params)
        rows = cur.fetchall()
    return {"rows": rows, "total": total}
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_engine_browser.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add databridge/engine/browser.py tests/test_engine_browser.py
git commit -m "feat: 数据浏览查询（分页/筛选/排序 + 白名单防注入）"
```

---

### Task 6: 行级写入 writer（追加 / N对N替换）

**Files:**
- Create: `databridge/engine/writer.py`
- Test: `tests/test_engine_writer.py`

**Interfaces:**
- Consumes: `ensure_identifier`（Task 4）、errors（Task 2）、`FakeConnection`（Task 3）
- Produces:
  - `fetch_rows_by_pk(conn, db, table, pk_cols: list[str], pk_values: list[list]) -> list[dict]`：按主键值列表读行，**保持入参顺序**返回；缺行抛 `InvalidQueryError`（提示哪个主键不存在）
  - `build_append_insert(db, table, columns: list[dict]) -> tuple[str, list[str]]`：返回 `(INSERT SQL, 参与列名列表)`；自增列被剔除
  - `append_rows(conn, db, table, columns, rows: list[dict]) -> int`：单事务追加，失败回滚重抛；返回插入行数
  - `replace_rows(conn, db, table, columns, pk_cols, src_rows: list[dict], dst_pk_values: list[list]) -> int`：按序配对 UPDATE（保留目标主键），单事务，失败回滚；数量不等抛 `SelectionCountMismatchError`
  - `build_upsert(db, table, columns: list[dict]) -> str`：`INSERT ... ON DUPLICATE KEY UPDATE`（全列含主键，供整表同步用）

- [ ] **Step 1: 写失败测试**

`tests/test_engine_writer.py`:

```python
"""行级写入测试：追加去自增、替换按序配对、事务回滚、upsert 语句。"""
import pytest

from databridge.engine import writer
from databridge.errors import InvalidQueryError, SelectionCountMismatchError
from tests.conftest import FakeConnection


def col(name, is_pk=False, is_autoinc=False):
    return {"name": name, "type": "int", "is_pk": is_pk, "is_autoinc": is_autoinc}

COLS_AUTOINC = [col("id", True, True), col("a"), col("b")]
COLS_PLAIN_PK = [col("code", True, False), col("a"), col("b")]


def test_build_append_insert_strips_autoinc():
    sql, names = writer.build_append_insert("d", "t", COLS_AUTOINC)
    assert sql == "INSERT INTO `d`.`t` (`a`, `b`) VALUES (%s, %s)"
    assert names == ["a", "b"]


def test_build_append_insert_keeps_non_autoinc_pk():
    sql, names = writer.build_append_insert("d", "t", COLS_PLAIN_PK)
    assert names == ["code", "a", "b"]


def test_append_rows_commits():
    conn = FakeConnection()
    n = writer.append_rows(conn, "d", "t", COLS_AUTOINC,
                           [{"id": 1, "a": 10, "b": 20}, {"id": 2, "a": 30, "b": 40}])
    assert n == 2
    assert conn.committed is True
    sql, batch = conn.cursor_obj.executed[0]
    assert batch == [[10, 20], [30, 40]]   # 自增 id 被剔除


def test_append_rows_rolls_back_on_error():
    conn = FakeConnection(error=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        writer.append_rows(conn, "d", "t", COLS_AUTOINC, [{"id": 1, "a": 1, "b": 2}])
    assert conn.rolled_back is True
    assert conn.committed is False


def test_replace_rows_count_mismatch():
    conn = FakeConnection()
    with pytest.raises(SelectionCountMismatchError):
        writer.replace_rows(conn, "d", "t", COLS_AUTOINC, ["id"],
                            src_rows=[{"id": 1, "a": 1, "b": 2}],
                            dst_pk_values=[[7], [8]])


def test_replace_rows_pairs_in_order():
    conn = FakeConnection()
    n = writer.replace_rows(
        conn, "d", "t", COLS_AUTOINC, ["id"],
        src_rows=[{"id": 1, "a": 10, "b": 20}, {"id": 2, "a": 30, "b": 40}],
        dst_pk_values=[[7], [8]])
    assert n == 2
    assert conn.committed is True
    sql1, params1 = conn.cursor_obj.executed[0]
    assert sql1 == "UPDATE `d`.`t` SET `a` = %s, `b` = %s WHERE `id` = %s"
    assert params1 == [10, 20, 7]          # 源第1行 -> 目标主键7，保留目标主键
    _, params2 = conn.cursor_obj.executed[1]
    assert params2 == [30, 40, 8]


def test_fetch_rows_by_pk_preserves_order_and_checks_missing():
    conn = FakeConnection(results=[[{"id": 2, "a": 1}, {"id": 1, "a": 2}]])
    rows = writer.fetch_rows_by_pk(conn, "d", "t", ["id"], [[1], [2]])
    assert [r["id"] for r in rows] == [1, 2]   # 按入参顺序返回

    conn2 = FakeConnection(results=[[{"id": 1, "a": 2}]])
    with pytest.raises(InvalidQueryError):
        writer.fetch_rows_by_pk(conn2, "d", "t", ["id"], [[1], [99]])


def test_build_upsert():
    sql = writer.build_upsert("d", "t", COLS_AUTOINC)
    assert sql == ("INSERT INTO `d`.`t` (`id`, `a`, `b`) VALUES (%s, %s, %s) "
                   "ON DUPLICATE KEY UPDATE `a` = VALUES(`a`), `b` = VALUES(`b`)")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_engine_writer.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 writer.py**

`databridge/engine/writer.py`:

```python
"""行级写入：追加(去自增主键)、N对N按序替换、upsert 语句生成。

全部写操作单事务：任一行失败整体回滚后重抛，由上层转成结构化错误。
"""
from databridge.engine.inspector import ensure_identifier
from databridge.errors import InvalidQueryError, SelectionCountMismatchError


def _qualify(db: str, table: str) -> str:
    ensure_identifier(db)
    ensure_identifier(table)
    return f"`{db}`.`{table}`"


def fetch_rows_by_pk(conn, db, table, pk_cols, pk_values):
    """按主键值列表读取行，保持入参顺序返回；有缺失主键立即报错。"""
    if not pk_values:
        return []
    target = _qualify(db, table)
    cond = " OR ".join(
        ["(" + " AND ".join([f"`{c}` = %s" for c in pk_cols]) + ")"] * len(pk_values))
    params = [v for pk in pk_values for v in pk]
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {target} WHERE {cond}", params)
        rows = cur.fetchall()
    # 按主键元组建索引，再按入参顺序输出
    index = {tuple(r[c] for c in pk_cols): r for r in rows}
    ordered = []
    for pk in pk_values:
        key = tuple(pk)
        if key not in index:
            raise InvalidQueryError(f"主键 {key} 在表 {db}.{table} 中不存在")
        ordered.append(index[key])
    return ordered


def build_append_insert(db, table, columns):
    """生成追加 INSERT：剔除自增列；非自增主键保留原样插入。"""
    names = [c["name"] for c in columns if not c["is_autoinc"]]
    cols_sql = ", ".join(f"`{n}`" for n in names)
    ph = ", ".join(["%s"] * len(names))
    return f"INSERT INTO {_qualify(db, table)} ({cols_sql}) VALUES ({ph})", names


def append_rows(conn, db, table, columns, rows) -> int:
    """单事务批量追加；失败回滚并重抛。返回插入行数。"""
    sql, names = build_append_insert(db, table, columns)
    batch = [[row[n] for n in names] for row in rows]
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, batch)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


def replace_rows(conn, db, table, columns, pk_cols, src_rows, dst_pk_values) -> int:
    """N对N按序替换：目标行保留自身主键，其余列用对应源行覆盖。"""
    if len(src_rows) != len(dst_pk_values):
        raise SelectionCountMismatchError(
            f"源勾选 {len(src_rows)} 行 / 目标勾选 {len(dst_pk_values)} 行，数量必须相等")
    set_cols = [c["name"] for c in columns if c["name"] not in pk_cols]
    set_sql = ", ".join(f"`{n}` = %s" for n in set_cols)
    where_sql = " AND ".join(f"`{c}` = %s" for c in pk_cols)
    sql = f"UPDATE {_qualify(db, table)} SET {set_sql} WHERE {where_sql}"
    try:
        with conn.cursor() as cur:
            for src_row, dst_pk in zip(src_rows, dst_pk_values):
                cur.execute(sql, [src_row[n] for n in set_cols] + list(dst_pk))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(src_rows)


def build_upsert(db, table, columns) -> str:
    """整表同步用：INSERT ... ON DUPLICATE KEY UPDATE（非主键列全覆盖）。"""
    names = [c["name"] for c in columns]
    non_pk = [c["name"] for c in columns if not c["is_pk"]]
    cols_sql = ", ".join(f"`{n}`" for n in names)
    ph = ", ".join(["%s"] * len(names))
    update_sql = ", ".join(f"`{n}` = VALUES(`{n}`)" for n in non_pk)
    return (f"INSERT INTO {_qualify(db, table)} ({cols_sql}) VALUES ({ph}) "
            f"ON DUPLICATE KEY UPDATE {update_sql}")
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_engine_writer.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add databridge/engine/writer.py tests/test_engine_writer.py
git commit -m "feat: 行级写入（追加去自增/N对N替换/upsert 语句 + 事务回滚）"
```

---

### Task 7: 整表增量比对 diff

**Files:**
- Create: `databridge/engine/diff.py`
- Test: `tests/test_engine_diff.py`

**Interfaces:**
- Consumes: `ensure_identifier`（Task 4）、`build_upsert`（Task 6）、`FakeConnection`（Task 3）
- Produces:
  - `iter_source_batches(conn, db, table, pk_cols, where: str | None = None, batch_size=1000)`：按主键排序 keyset 分批读源表的生成器
  - `classify_batch(src_batch: list[dict], dst_rows: list[dict], pk_cols: list[str]) -> tuple[list[dict], list[dict]]`：返回 `(目标缺失的新增行, 内容不同的变更行)`
  - `preview_diff(src_conn, dst_conn, src_db, src_table, dst_db, dst_table, columns, pk_cols, where=None, batch_size=1000) -> dict`：`{"to_insert": int, "to_update": int, "sample_pks": list}`（sample_pks 最多 10 个），不写任何数据
  - `execute_diff_sync(src_conn, dst_conn, src_db, src_table, dst_db, dst_table, columns, pk_cols, where=None, batch_size=1000) -> dict`：分批 upsert，`{"inserted": int, "updated": int}`；失败回滚重抛

- [ ] **Step 1: 写失败测试**

`tests/test_engine_diff.py`:

```python
"""整表增量比对测试：新增/变更判定、preview 统计、execute upsert。"""
from databridge.engine import diff
from tests.conftest import FakeConnection


def col(name, is_pk=False, is_autoinc=False):
    return {"name": name, "type": "int", "is_pk": is_pk, "is_autoinc": is_autoinc}

COLS = [col("id", True), col("v")]


def test_classify_batch():
    src = [{"id": 1, "v": 10}, {"id": 2, "v": 20}, {"id": 3, "v": 30}]
    dst = [{"id": 1, "v": 10},   # 相同 -> 跳过
           {"id": 2, "v": 99}]   # 不同 -> 变更；id=3 目标缺失 -> 新增
    inserts, updates = diff.classify_batch(src, dst, ["id"])
    assert [r["id"] for r in inserts] == [3]
    assert [r["id"] for r in updates] == [2]


def test_preview_diff_counts():
    # 源第一批返回 3 行，第二批返回空(结束)；目标按主键查回 2 行
    src_conn = FakeConnection(results=[
        [{"id": 1, "v": 10}, {"id": 2, "v": 20}, {"id": 3, "v": 30}],
        [],
    ])
    dst_conn = FakeConnection(results=[
        [{"id": 1, "v": 10}, {"id": 2, "v": 99}],
    ])
    out = diff.preview_diff(src_conn, dst_conn, "s", "t1", "d", "t2",
                            COLS, ["id"], batch_size=10)
    assert out == {"to_insert": 1, "to_update": 1, "sample_pks": [[3], [2]]}
    assert dst_conn.committed is False   # 预览绝不写数据


def test_execute_diff_sync_upserts_only_changed():
    src_conn = FakeConnection(results=[
        [{"id": 1, "v": 10}, {"id": 2, "v": 20}, {"id": 3, "v": 30}],
        [],
    ])
    dst_conn = FakeConnection(results=[
        [{"id": 1, "v": 10}, {"id": 2, "v": 99}],
    ])
    out = diff.execute_diff_sync(src_conn, dst_conn, "s", "t1", "d", "t2",
                                 COLS, ["id"], batch_size=10)
    assert out == {"inserted": 1, "updated": 1}
    assert dst_conn.committed is True
    # 找到 executemany 的 upsert 调用：只带 id=3(新增) 和 id=2(变更) 两行
    upsert_calls = [(s, p) for s, p in dst_conn.cursor_obj.executed
                    if s.startswith("INSERT INTO")]
    assert len(upsert_calls) == 1
    assert upsert_calls[0][1] == [[3, 30], [2, 20]]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_engine_diff.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 diff.py**

`databridge/engine/diff.py`:

```python
"""整表增量比对：主键逐行、keyset 分批，preview 只读、execute 分批 upsert。"""
from databridge.engine.inspector import ensure_identifier
from databridge.engine.writer import build_upsert

_SAMPLE_LIMIT = 10  # preview 返回的主键示例上限


def _qualify(db, table):
    ensure_identifier(db)
    ensure_identifier(table)
    return f"`{db}`.`{table}`"


def _pk_tuple(row, pk_cols):
    return tuple(row[c] for c in pk_cols)


def iter_source_batches(conn, db, table, pk_cols, where=None, batch_size=1000):
    """按主键排序 keyset 分页逐批读源表。where 为可选的原样 SQL 条件。

    注意：where 由使用者（GUI 输入）提供，仅用于源表读取，不参与写入拼接。
    """
    target = _qualify(db, table)
    order = ", ".join(f"`{c}`" for c in pk_cols)
    last_pk = None
    while True:
        conds, params = [], []
        if where:
            conds.append(f"({where})")
        if last_pk is not None:
            # 复合主键用行值比较实现 keyset 分页
            pk_expr = "(" + ", ".join(f"`{c}`" for c in pk_cols) + ")"
            conds.append(f"{pk_expr} > (" + ", ".join(["%s"] * len(pk_cols)) + ")")
            params.extend(last_pk)
        where_sql = (" WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"SELECT * FROM {target}{where_sql} ORDER BY {order} LIMIT %s"
        with conn.cursor() as cur:
            cur.execute(sql, params + [batch_size])
            batch = cur.fetchall()
        if not batch:
            return
        yield batch
        last_pk = _pk_tuple(batch[-1], pk_cols)


def _fetch_dst_rows(dst_conn, dst_db, dst_table, pk_cols, src_batch):
    """按源批次的主键集合查目标表现有行。"""
    target = _qualify(dst_db, dst_table)
    cond = " OR ".join(
        ["(" + " AND ".join(f"`{c}` = %s" for c in pk_cols) + ")"] * len(src_batch))
    params = [v for row in src_batch for v in _pk_tuple(row, pk_cols)]
    with dst_conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {target} WHERE {cond}", params)
        return cur.fetchall()


def classify_batch(src_batch, dst_rows, pk_cols):
    """比对一批：返回 (目标缺失的新增行, 内容不同的变更行)。"""
    dst_index = {_pk_tuple(r, pk_cols): r for r in dst_rows}
    inserts, updates = [], []
    for row in src_batch:
        dst = dst_index.get(_pk_tuple(row, pk_cols))
        if dst is None:
            inserts.append(row)
        elif dict(dst) != dict(row):
            updates.append(row)
    return inserts, updates


def preview_diff(src_conn, dst_conn, src_db, src_table, dst_db, dst_table,
                 columns, pk_cols, where=None, batch_size=1000):
    """dry-run：统计将新增/覆盖的行数与主键示例，不写任何数据。"""
    to_insert = to_update = 0
    sample_pks = []
    for batch in iter_source_batches(src_conn, src_db, src_table,
                                     pk_cols, where, batch_size):
        dst_rows = _fetch_dst_rows(dst_conn, dst_db, dst_table, pk_cols, batch)
        inserts, updates = classify_batch(batch, dst_rows, pk_cols)
        to_insert += len(inserts)
        to_update += len(updates)
        for row in inserts + updates:
            if len(sample_pks) < _SAMPLE_LIMIT:
                sample_pks.append(list(_pk_tuple(row, pk_cols)))
    return {"to_insert": to_insert, "to_update": to_update,
            "sample_pks": sample_pks}


def execute_diff_sync(src_conn, dst_conn, src_db, src_table, dst_db, dst_table,
                      columns, pk_cols, where=None, batch_size=1000):
    """执行同步：逐批 upsert 差异行（新增+变更），失败回滚重抛。"""
    names = [c["name"] for c in columns]
    upsert_sql = build_upsert(dst_db, dst_table, columns)
    inserted = updated = 0
    try:
        for batch in iter_source_batches(src_conn, src_db, src_table,
                                         pk_cols, where, batch_size):
            dst_rows = _fetch_dst_rows(dst_conn, dst_db, dst_table, pk_cols, batch)
            inserts, updates = classify_batch(batch, dst_rows, pk_cols)
            changed = inserts + updates
            if changed:
                values = [[row[n] for n in names] for row in changed]
                with dst_conn.cursor() as cur:
                    cur.executemany(upsert_sql, values)
            inserted += len(inserts)
            updated += len(updates)
        dst_conn.commit()
    except Exception:
        dst_conn.rollback()
        raise
    return {"inserted": inserted, "updated": updated}
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_engine_diff.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add databridge/engine/diff.py tests/test_engine_diff.py
git commit -m "feat: 整表增量比对（keyset 分批 + preview/execute）"
```

---

### Task 8: 服务层 service（护栏 + 用例编排）

**Files:**
- Create: `databridge/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `ConnectionStore`（Task 2）、`open_connection`（Task 3）、inspector（Task 4）、browser（Task 5）、writer（Task 6）、diff（Task 7）
- Produces: `SyncService(store: ConnectionStore, connect=open_connection)`（`connect` 可注入 fake 供测试），方法：
  - `browse_table(alias, db, table, page=1, page_size=50, filters=None, sort_column=None, sort_dir="asc") -> dict`（在 browse 结果上附加 `columns` 元数据供前端建列）
  - `list_databases(alias) -> list[str]`、`list_tables(alias, db) -> list[str]`
  - `insert_rows(src: dict, dst: dict, pk_values: list[list], confirm: bool = False) -> dict`；src/dst 均为 `{"alias","db","table"}`；返回 `{"inserted": int}`
  - `replace_rows(src, dst, src_pk_values, dst_pk_values, confirm=False) -> dict`；返回 `{"replaced": int}`
  - `preview_sync(src, dst, where=None) -> dict`（透传 diff.preview_diff 结果）
  - `execute_sync(src, dst, where=None, confirm=False) -> dict`（透传 diff.execute_diff_sync 结果）
  - 内部 `_guard_write(dst_alias, confirm)`：目标连接 `protected=True` 且未 confirm 时抛 `ProtectedConnectionError`；**所有写方法第一行先过此护栏**

- [ ] **Step 1: 写失败测试**

`tests/test_service.py`:

```python
"""服务层测试：受保护连接护栏、insert/replace 编排（fake 连接注入）。"""
import pytest

from databridge.errors import ProtectedConnectionError
from databridge.service import SyncService
from databridge.storage.connections import ConnectionInfo, ConnectionStore
from tests.conftest import FakeConnection


@pytest.fixture
def store(tmp_path):
    s = ConnectionStore(tmp_path)
    s.save(ConnectionInfo(alias="dev", host="h", port=3306, user="u",
                          password="p", default_db=None, protected=False))
    s.save(ConnectionInfo(alias="prod", host="h", port=3306, user="u",
                          password="p", default_db=None, protected=True))
    return s

SRC = {"alias": "dev", "db": "s", "table": "t"}
DST_PROD = {"alias": "prod", "db": "d", "table": "t"}

COL_META = [
    {"name": "id", "type": "int", "is_pk": 1, "is_autoinc": 1},
    {"name": "a", "type": "int", "is_pk": 0, "is_autoinc": 0},
]


def test_write_to_protected_without_confirm_rejected(store):
    svc = SyncService(store, connect=lambda info, db=None: FakeConnection())
    with pytest.raises(ProtectedConnectionError) as ei:
        svc.insert_rows(SRC, DST_PROD, pk_values=[[1]], confirm=False)
    assert "受保护" in ei.value.message


def test_replace_and_execute_also_guarded(store):
    svc = SyncService(store, connect=lambda info, db=None: FakeConnection())
    with pytest.raises(ProtectedConnectionError):
        svc.replace_rows(SRC, DST_PROD, [[1]], [[2]], confirm=False)
    with pytest.raises(ProtectedConnectionError):
        svc.execute_sync(SRC, DST_PROD, confirm=False)


def test_insert_rows_happy_path(store):
    # 依连接打开顺序注入结果集：
    # 源连接：get_columns、fetch_rows_by_pk；目标连接：get_columns
    conns = [
        FakeConnection(results=[COL_META, [{"id": 1, "a": 10}]]),   # 源
        FakeConnection(results=[COL_META]),                          # 目标
    ]
    svc = SyncService(store, connect=lambda info, db=None: conns.pop(0))
    out = svc.insert_rows(SRC, {"alias": "dev", "db": "d", "table": "t"},
                          pk_values=[[1]], confirm=False)
    assert out == {"inserted": 1}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_service.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'databridge.service'`

- [ ] **Step 3: 实现 service.py**

`databridge/service.py`:

```python
"""服务层：连接解析 + 安全护栏 + 引擎用例编排。

Web 层（未来 MCP 层）只调用本模块，不直接触碰引擎细节。
"""
from contextlib import closing

from databridge.engine import browser, diff, inspector, writer
from databridge.engine.connection import open_connection
from databridge.errors import ProtectedConnectionError
from databridge.storage.connections import ConnectionStore


class SyncService:
    """同步服务门面。connect 参数可注入以便测试。"""

    def __init__(self, store: ConnectionStore, connect=open_connection):
        self._store = store
        self._connect = connect

    # ---------- 护栏 ----------

    def _guard_write(self, dst_alias: str, confirm: bool) -> None:
        """写入受保护连接必须显式 confirm=True，否则拒绝。"""
        info = self._store.get(dst_alias)
        if info.protected and not confirm:
            raise ProtectedConnectionError(
                f"连接 {dst_alias} 为受保护连接，写入必须显式确认（confirm=true）")

    def _open(self, alias: str, db: str | None = None):
        return self._connect(self._store.get(alias), db)

    # ---------- 浏览 ----------

    def browse_table(self, alias, db, table, page=1, page_size=50,
                     filters=None, sort_column=None, sort_dir="asc") -> dict:
        with closing(self._open(alias)) as conn:
            columns = inspector.get_columns(conn, db, table)
            out = browser.browse(conn, db, table, columns, page, page_size,
                                 filters, sort_column, sort_dir)
        out["columns"] = columns
        return out

    def list_databases(self, alias) -> list[str]:
        with closing(self._open(alias)) as conn:
            return inspector.list_databases(conn)

    def list_tables(self, alias, db) -> list[str]:
        with closing(self._open(alias)) as conn:
            return inspector.list_tables(conn, db)

    # ---------- 勾选行同步 ----------

    def insert_rows(self, src, dst, pk_values, confirm=False) -> dict:
        """把源表勾选行（主键列表）追加到目标表。"""
        self._guard_write(dst["alias"], confirm)
        with closing(self._open(src["alias"])) as src_conn, \
                closing(self._open(dst["alias"])) as dst_conn:
            src_cols = inspector.get_columns(src_conn, src["db"], src["table"])
            dst_cols = inspector.get_columns(dst_conn, dst["db"], dst["table"])
            inspector.check_columns_match(src_cols, dst_cols)
            pk_cols = inspector.get_primary_key(src_cols, src["db"], src["table"])
            rows = writer.fetch_rows_by_pk(
                src_conn, src["db"], src["table"], pk_cols, pk_values)
            n = writer.append_rows(
                dst_conn, dst["db"], dst["table"], dst_cols, rows)
        return {"inserted": n}

    def replace_rows(self, src, dst, src_pk_values, dst_pk_values,
                     confirm=False) -> dict:
        """N对N按勾选顺序替换目标行（保留目标主键）。"""
        self._guard_write(dst["alias"], confirm)
        with closing(self._open(src["alias"])) as src_conn, \
                closing(self._open(dst["alias"])) as dst_conn:
            src_cols = inspector.get_columns(src_conn, src["db"], src["table"])
            dst_cols = inspector.get_columns(dst_conn, dst["db"], dst["table"])
            inspector.check_columns_match(src_cols, dst_cols)
            src_pk = inspector.get_primary_key(src_cols, src["db"], src["table"])
            dst_pk = inspector.get_primary_key(dst_cols, dst["db"], dst["table"])
            rows = writer.fetch_rows_by_pk(
                src_conn, src["db"], src["table"], src_pk, src_pk_values)
            n = writer.replace_rows(
                dst_conn, dst["db"], dst["table"], dst_cols, dst_pk,
                rows, dst_pk_values)
        return {"replaced": n}

    # ---------- 整表同步 ----------

    def _sync_prepare(self, src_conn, dst_conn, src, dst):
        """整表同步共用前置校验，返回 (columns, pk_cols)。"""
        src_cols = inspector.get_columns(src_conn, src["db"], src["table"])
        dst_cols = inspector.get_columns(dst_conn, dst["db"], dst["table"])
        inspector.check_pk_match(src_cols, dst_cols)
        inspector.check_columns_match(src_cols, dst_cols)
        pk_cols = inspector.get_primary_key(src_cols, src["db"], src["table"])
        return src_cols, pk_cols

    def preview_sync(self, src, dst, where=None) -> dict:
        with closing(self._open(src["alias"])) as src_conn, \
                closing(self._open(dst["alias"])) as dst_conn:
            columns, pk_cols = self._sync_prepare(src_conn, dst_conn, src, dst)
            return diff.preview_diff(
                src_conn, dst_conn, src["db"], src["table"],
                dst["db"], dst["table"], columns, pk_cols, where)

    def execute_sync(self, src, dst, where=None, confirm=False) -> dict:
        self._guard_write(dst["alias"], confirm)
        with closing(self._open(src["alias"])) as src_conn, \
                closing(self._open(dst["alias"])) as dst_conn:
            columns, pk_cols = self._sync_prepare(src_conn, dst_conn, src, dst)
            return diff.execute_diff_sync(
                src_conn, dst_conn, src["db"], src["table"],
                dst["db"], dst["table"], columns, pk_cols, where)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_service.py -v`
Expected: 3 passed
Run: `uv run pytest -v`（全量回归）
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add databridge/service.py tests/test_service.py
git commit -m "feat: 服务层（受保护连接护栏 + 用例编排）"
```

---

### Task 9: FastAPI Web API 层

**Files:**
- Create: `databridge/web/app.py`
- Test: `tests/test_web_api.py`

**Interfaces:**
- Consumes: `SyncService`（Task 8）、`ConnectionStore`/`ConnectionInfo`（Task 2）、`check_connection`（Task 3）、`DataBridgeError`（Task 2）
- Produces:
  - `create_app(data_dir: Path | None = None) -> FastAPI`（data_dir 默认项目根 `data/`，测试可注入 tmp_path）
  - REST 路由（全部 JSON）：
    - `GET /api/connections`（list_safe，无密码）、`POST /api/connections`（新增/更新）、`DELETE /api/connections/{alias}`、`POST /api/connections/test`
    - `GET /api/databases?alias=`、`GET /api/tables?alias=&db=`
    - `POST /api/browse`（body：alias/db/table/page/page_size/filters/sort_column/sort_dir）
    - `POST /api/rows/insert`、`POST /api/rows/replace`
    - `POST /api/sync/preview`、`POST /api/sync/execute`
  - 统一异常处理：`DataBridgeError -> JSONResponse(status_code=e.http_status, {"code", "message"})`；其它异常 -> 500 `{"code": "internal_error", "message": "服务内部错误：...类名"}`（不回显异常原文，防泄密）
  - `/` 挂载 `databridge/web/static/` 静态目录（html=True）

- [ ] **Step 1: 写失败测试**

`tests/test_web_api.py`:

```python
"""Web API 冒烟测试：连接 CRUD、护栏 403、错误结构、无密码回显。"""
import pytest
from fastapi.testclient import TestClient

from databridge.web.app import create_app

CONN_BODY = {"alias": "dev", "host": "127.0.0.1", "port": 3306, "user": "root",
             "password": "pw!", "default_db": None, "protected": False}
PROD_BODY = dict(CONN_BODY, alias="prod", protected=True)


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=tmp_path)
    return TestClient(app)


def test_connection_crud_and_no_password_leak(client):
    r = client.post("/api/connections", json=CONN_BODY)
    assert r.status_code == 200
    r = client.get("/api/connections")
    assert r.status_code == 200
    assert r.json() == [{"alias": "dev", "host": "127.0.0.1", "port": 3306,
                         "user": "root", "default_db": None, "protected": False}]
    assert "pw!" not in r.text
    r = client.delete("/api/connections/dev")
    assert r.status_code == 200
    assert client.get("/api/connections").json() == []


def test_delete_missing_connection_404(client):
    r = client.delete("/api/connections/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "connection_not_found"
    assert "不存在" in body["message"]


def test_protected_write_without_confirm_403(client):
    client.post("/api/connections", json=CONN_BODY)
    client.post("/api/connections", json=PROD_BODY)
    r = client.post("/api/rows/insert", json={
        "src": {"alias": "dev", "db": "s", "table": "t"},
        "dst": {"alias": "prod", "db": "d", "table": "t"},
        "pk_values": [[1]], "confirm": False})
    assert r.status_code == 403
    assert r.json()["code"] == "protected_connection"


def test_sync_execute_also_guarded(client):
    client.post("/api/connections", json=CONN_BODY)
    client.post("/api/connections", json=PROD_BODY)
    r = client.post("/api/sync/execute", json={
        "src": {"alias": "dev", "db": "s", "table": "t"},
        "dst": {"alias": "prod", "db": "d", "table": "t"},
        "confirm": False})
    assert r.status_code == 403
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_web_api.py -v`
Expected: FAIL，`ImportError: cannot import name 'create_app'`

- [ ] **Step 3: 实现 app.py**

`databridge/web/app.py`:

```python
"""Web 入口：FastAPI 路由薄壳，业务全部委托 SyncService。

启动：uv run uvicorn databridge.web.app:app --port 8000
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from databridge.engine.connection import check_connection
from databridge.errors import DataBridgeError
from databridge.service import SyncService
from databridge.storage.connections import ConnectionInfo, ConnectionStore

_STATIC_DIR = Path(__file__).parent / "static"


# ---------- 请求体模型 ----------

class ConnBody(BaseModel):
    alias: str
    host: str
    port: int = 3306
    user: str
    password: str = ""          # 更新时留空表示保留旧密码
    default_db: str | None = None
    protected: bool = False


class TableRef(BaseModel):
    alias: str
    db: str
    table: str


class BrowseBody(BaseModel):
    alias: str
    db: str
    table: str
    page: int = 1
    page_size: int = 50
    filters: list[dict] | None = None
    sort_column: str | None = None
    sort_dir: str = "asc"


class InsertBody(BaseModel):
    src: TableRef
    dst: TableRef
    pk_values: list[list]
    confirm: bool = False


class ReplaceBody(BaseModel):
    src: TableRef
    dst: TableRef
    src_pk_values: list[list]
    dst_pk_values: list[list]
    confirm: bool = False


class SyncBody(BaseModel):
    src: TableRef
    dst: TableRef
    where: str | None = None
    confirm: bool = False


def create_app(data_dir: Path | None = None) -> FastAPI:
    """创建应用；data_dir 可注入临时目录供测试。"""
    store = ConnectionStore(data_dir or Path("data"))
    svc = SyncService(store)
    app = FastAPI(title="DataBridge")

    @app.exception_handler(DataBridgeError)
    async def on_business_error(request: Request, exc: DataBridgeError):
        return JSONResponse(status_code=exc.http_status,
                            content={"code": exc.code, "message": exc.message})

    @app.exception_handler(Exception)
    async def on_unknown_error(request: Request, exc: Exception):
        # 不回显异常原文，避免凭据泄露；只给异常类名
        return JSONResponse(status_code=500, content={
            "code": "internal_error",
            "message": f"服务内部错误：{type(exc).__name__}"})

    # ---------- 连接管理 ----------

    @app.get("/api/connections")
    def list_connections():
        return store.list_safe()

    @app.post("/api/connections")
    def save_connection(body: ConnBody):
        store.save(ConnectionInfo(**body.model_dump()))
        return {"ok": True}

    @app.delete("/api/connections/{alias}")
    def delete_connection(alias: str):
        store.delete(alias)
        return {"ok": True}

    @app.post("/api/connections/test")
    def test_connection(body: ConnBody):
        info = ConnectionInfo(**body.model_dump())
        if body.password == "":
            # 编辑态不改密码时，用已存密码测试
            info = store.get(body.alias)
        ok = check_connection(info)
        return {"ok": ok}

    # ---------- 元数据与浏览 ----------

    @app.get("/api/databases")
    def list_databases(alias: str):
        return svc.list_databases(alias)

    @app.get("/api/tables")
    def list_tables(alias: str, db: str):
        return svc.list_tables(alias, db)

    @app.post("/api/browse")
    def browse(body: BrowseBody):
        return svc.browse_table(body.alias, body.db, body.table, body.page,
                                body.page_size, body.filters,
                                body.sort_column, body.sort_dir)

    # ---------- 勾选行同步 ----------

    @app.post("/api/rows/insert")
    def rows_insert(body: InsertBody):
        return svc.insert_rows(body.src.model_dump(), body.dst.model_dump(),
                               body.pk_values, body.confirm)

    @app.post("/api/rows/replace")
    def rows_replace(body: ReplaceBody):
        return svc.replace_rows(body.src.model_dump(), body.dst.model_dump(),
                                body.src_pk_values, body.dst_pk_values,
                                body.confirm)

    # ---------- 整表同步 ----------

    @app.post("/api/sync/preview")
    def sync_preview(body: SyncBody):
        return svc.preview_sync(body.src.model_dump(), body.dst.model_dump(),
                                body.where)

    @app.post("/api/sync/execute")
    def sync_execute(body: SyncBody):
        return svc.execute_sync(body.src.model_dump(), body.dst.model_dump(),
                                body.where, body.confirm)

    # 静态页面（前端在 Task 10 交付；目录不存在时跳过，保证测试可跑）
    if _STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
    return app


app = create_app()
```

注意：`TestClient` 默认 `raise_server_exceptions=True` 会把 500 异常直接抛出；本任务测试里只断言业务错误（403/404），不受影响。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_web_api.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add databridge/web/app.py tests/test_web_api.py
git commit -m "feat: FastAPI Web API（连接CRUD/浏览/行同步/整表同步 + 统一错误处理）"
```

---

### Task 10: 前端骨架 + 连接管理页

> 前端任务无法单测，验证方式为：启动服务后浏览器手工验证（步骤内给出验证清单）。

**Files:**
- Create: `databridge/web/static/index.html`
- Create: `databridge/web/static/js/api.js`
- Create: `databridge/web/static/js/connections.js`
- Create: `databridge/web/static/js/browser.js`（本任务先建空文件，Task 11 填充）
- Create: `databridge/web/static/js/sync.js`（本任务先建空文件，Task 12 填充）
- Create: `databridge/web/static/vendor/tabulator.min.js`、`databridge/web/static/vendor/tabulator.min.css`（下载 vendor）

**Interfaces:**
- Consumes: Task 9 的全部 REST API
- Produces:
  - 全局函数 `api(method, path, body) -> Promise`（失败时 throw Error(message) 并自动 toast）
  - `toast(msg, isError)`、`showConfirm(summaryHtml, {requireProtected}) -> Promise<bool>`（受保护时带「我确认写入受保护库」复选框，不勾不可确认）
  - `loadConnections() -> Promise<list>`（带缓存，供各页复用；含 protected 标记）
  - 页面容器：`#tab-connections` / `#tab-browser` / `#tab-sync` 三个 tab 区域，Task 11/12 在其中渲染

- [ ] **Step 1: 下载 Tabulator vendor 文件**

Run（PowerShell）:

```powershell
New-Item -ItemType Directory -Force databridge/web/static/vendor, databridge/web/static/js
Invoke-WebRequest https://unpkg.com/tabulator-tables@5.6.1/dist/js/tabulator.min.js -OutFile databridge/web/static/vendor/tabulator.min.js
Invoke-WebRequest https://unpkg.com/tabulator-tables@5.6.1/dist/css/tabulator.min.css -OutFile databridge/web/static/vendor/tabulator.min.css
```

Expected: 两个 vendor 文件存在且非空。同时创建空文件 `js/browser.js`、`js/sync.js`。

- [ ] **Step 2: 写 index.html**

`databridge/web/static/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>DataBridge - MySQL 数据同步</title>
<link rel="stylesheet" href="/vendor/tabulator.min.css">
<style>
  body { font-family: "Microsoft YaHei", sans-serif; margin: 0; background: #f5f6f8; }
  header { background: #1f2937; color: #fff; padding: 10px 20px; display: flex; gap: 20px; align-items: center; }
  header h1 { font-size: 18px; margin: 0 30px 0 0; }
  header button { background: none; border: none; color: #cbd5e1; font-size: 14px; cursor: pointer; padding: 6px 10px; }
  header button.active { color: #fff; border-bottom: 2px solid #60a5fa; }
  main { padding: 16px 20px; }
  .tab { display: none; }
  .tab.active { display: block; }
  .card { background: #fff; border-radius: 8px; padding: 14px; margin-bottom: 14px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  label { font-size: 13px; margin-right: 4px; }
  input, select { padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 5px; font-size: 13px; }
  button.btn { padding: 6px 14px; border: none; border-radius: 5px; background: #2563eb; color: #fff; cursor: pointer; font-size: 13px; }
  button.btn.gray { background: #6b7280; }
  button.btn.red { background: #dc2626; }
  table.plain { border-collapse: collapse; width: 100%; font-size: 13px; }
  table.plain th, table.plain td { border: 1px solid #e5e7eb; padding: 6px 10px; text-align: left; }
  #toast { position: fixed; top: 16px; right: 16px; z-index: 999; }
  .toast-item { background: #16a34a; color: #fff; padding: 10px 16px; border-radius: 6px; margin-bottom: 8px; font-size: 13px; }
  .toast-item.err { background: #dc2626; }
  #modal-mask { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 900; }
  #modal { background: #fff; border-radius: 8px; max-width: 560px; margin: 10vh auto; padding: 18px; max-height: 70vh; overflow: auto; }
  .grid-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  .selinfo { font-size: 12px; color: #2563eb; }
</style>
</head>
<body>
<header>
  <h1>DataBridge</h1>
  <button data-tab="connections" class="active">连接管理</button>
  <button data-tab="browser">数据浏览器</button>
  <button data-tab="sync">整表同步</button>
</header>
<main>
  <div id="tab-connections" class="tab active"></div>
  <div id="tab-browser" class="tab"></div>
  <div id="tab-sync" class="tab"></div>
</main>
<div id="toast"></div>
<div id="modal-mask"><div id="modal"></div></div>
<script src="/vendor/tabulator.min.js"></script>
<script src="/js/api.js"></script>
<script src="/js/connections.js"></script>
<script src="/js/browser.js"></script>
<script src="/js/sync.js"></script>
<script>
  // tab 切换
  document.querySelectorAll('header button[data-tab]').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('header button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    };
  });
</script>
</body>
</html>
```

- [ ] **Step 3: 写 api.js（请求/toast/确认框/连接缓存）**

`databridge/web/static/js/api.js`:

```javascript
// 公共工具：API 请求、toast、确认框、连接列表缓存

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* 非 JSON 响应 */ }
  if (!res.ok) {
    const msg = data.message || ('请求失败 HTTP ' + res.status);
    toast(msg, true);
    throw new Error(msg);
  }
  return data;
}

function toast(msg, isError) {
  const el = document.createElement('div');
  el.className = 'toast-item' + (isError ? ' err' : '');
  el.textContent = msg;
  document.getElementById('toast').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// 确认框：requireProtected 时必须勾选确认复选框才能点「确认执行」
function showConfirm(summaryHtml, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    const mask = document.getElementById('modal-mask');
    const modal = document.getElementById('modal');
    modal.innerHTML = `
      <h3>确认操作</h3>
      <div>${summaryHtml}</div>
      ${opts.requireProtected ? `
        <p style="color:#dc2626"><label>
          <input type="checkbox" id="m-protect"> 目标为受保护连接，我确认写入受保护库
        </label></p>` : ''}
      <div style="margin-top:12px;text-align:right">
        <button class="btn gray" id="m-cancel">取消</button>
        <button class="btn" id="m-ok">确认执行</button>
      </div>`;
    mask.style.display = 'block';
    const close = val => { mask.style.display = 'none'; resolve(val); };
    modal.querySelector('#m-cancel').onclick = () => close(false);
    modal.querySelector('#m-ok').onclick = () => {
      if (opts.requireProtected && !modal.querySelector('#m-protect').checked) {
        toast('请先勾选受保护库写入确认', true);
        return;
      }
      close(true);
    };
  });
}

// 连接列表缓存（含 protected 标记），保存/删除连接后需 invalidateConnections()
let _connCache = null;
async function loadConnections() {
  if (!_connCache) _connCache = await api('GET', '/api/connections');
  return _connCache;
}
function invalidateConnections() { _connCache = null; }
```

- [ ] **Step 4: 写 connections.js（连接管理页）**

`databridge/web/static/js/connections.js`:

```javascript
// 连接管理页：列表 + 表单（新增/编辑）+ 测试连接 + 删除
(function () {
  const root = document.getElementById('tab-connections');
  root.innerHTML = `
    <div class="card">
      <h3>连接列表</h3>
      <table class="plain" id="conn-table">
        <thead><tr><th>别名</th><th>主机</th><th>端口</th><th>用户</th>
        <th>默认库</th><th>受保护</th><th>操作</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="card">
      <h3 id="conn-form-title">新增连接</h3>
      <div class="grid-toolbar">
        <label>别名 <input id="c-alias"></label>
        <label>主机 <input id="c-host"></label>
        <label>端口 <input id="c-port" type="number" value="3306" style="width:70px"></label>
        <label>用户 <input id="c-user"></label>
        <label>密码 <input id="c-pass" type="password" placeholder="编辑时留空=不修改"></label>
        <label>默认库 <input id="c-db" placeholder="可选"></label>
        <label><input id="c-prot" type="checkbox"> 受保护</label>
      </div>
      <button class="btn" id="c-save">保存</button>
      <button class="btn gray" id="c-test">测试连接</button>
      <button class="btn gray" id="c-reset">清空</button>
    </div>`;

  function formBody() {
    return {
      alias: document.getElementById('c-alias').value.trim(),
      host: document.getElementById('c-host').value.trim(),
      port: parseInt(document.getElementById('c-port').value, 10) || 3306,
      user: document.getElementById('c-user').value.trim(),
      password: document.getElementById('c-pass').value,
      default_db: document.getElementById('c-db').value.trim() || null,
      protected: document.getElementById('c-prot').checked,
    };
  }

  function fillForm(c) {
    document.getElementById('c-alias').value = c ? c.alias : '';
    document.getElementById('c-host').value = c ? c.host : '';
    document.getElementById('c-port').value = c ? c.port : 3306;
    document.getElementById('c-user').value = c ? c.user : '';
    document.getElementById('c-pass').value = '';
    document.getElementById('c-db').value = c && c.default_db ? c.default_db : '';
    document.getElementById('c-prot').checked = c ? c.protected : false;
    document.getElementById('conn-form-title').textContent =
      c ? ('编辑连接：' + c.alias) : '新增连接';
  }

  async function refresh() {
    invalidateConnections();
    const list = await loadConnections();
    const tbody = document.querySelector('#conn-table tbody');
    tbody.innerHTML = '';
    list.forEach(c => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${c.alias}</td><td>${c.host}</td><td>${c.port}</td>
        <td>${c.user}</td><td>${c.default_db || '-'}</td>
        <td>${c.protected ? '✅' : ''}</td>
        <td><button class="btn gray" data-edit="${c.alias}">编辑</button>
            <button class="btn red" data-del="${c.alias}">删除</button></td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('[data-edit]').forEach(b => b.onclick = () =>
      fillForm(list.find(c => c.alias === b.dataset.edit)));
    tbody.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      if (!await showConfirm(`删除连接 <b>${b.dataset.del}</b>？`)) return;
      await api('DELETE', '/api/connections/' + encodeURIComponent(b.dataset.del));
      toast('已删除');
      refresh();
    });
  }

  document.getElementById('c-save').onclick = async () => {
    const body = formBody();
    if (!body.alias || !body.host || !body.user) { toast('别名/主机/用户必填', true); return; }
    await api('POST', '/api/connections', body);
    toast('已保存');
    fillForm(null);
    refresh();
  };
  document.getElementById('c-test').onclick = async () => {
    const out = await api('POST', '/api/connections/test', formBody());
    toast(out.ok ? '连接成功' : '连接失败', !out.ok);
  };
  document.getElementById('c-reset').onclick = () => fillForm(null);

  refresh();
})();
```

- [ ] **Step 5: 启动服务手工验证**

Run: `uv run uvicorn databridge.web.app:app --port 8000`

浏览器打开 `http://127.0.0.1:8000/`，验证清单：
1. 页面正常渲染，三个 tab 可切换；
2. 新增一个连接（可用本地 MySQL，无则填假值），列表出现该行；
3. 有真实 MySQL 时点「测试连接」提示成功；填错密码时 toast 报错且不含密码；
4. 编辑时密码留空保存，再次测试连接仍成功（旧密码保留）；
5. 删除连接弹确认框，确认后列表移除；
6. `data/connections.json` 中看不到明文密码。

- [ ] **Step 6: Commit**

```bash
git add databridge/web/static
git commit -m "feat: 前端骨架 + 连接管理页（vendor Tabulator）"
```

---

### Task 11: 数据浏览器双网格 + 勾选行同步（新功能核心）

**Files:**
- Modify: `databridge/web/static/js/browser.js`（Task 10 建的空文件，写入全部内容）

**Interfaces:**
- Consumes: `api/toast/showConfirm/loadConnections`（Task 10）、`POST /api/browse`、`POST /api/rows/insert`、`POST /api/rows/replace`、`GET /api/databases`、`GET /api/tables`（Task 9）、Tabulator（vendor）
- Produces: 数据浏览器页完整交互：源/目标双网格、列筛选排序分页、跨页勾选（记录勾选顺序）、新增/替换按钮 + 确认流程

关键设计：
- Tabulator 远程模式（分页/排序/筛选均 remote），`ajaxRequestFunc` 转调 `POST /api/browse`；
- 每行计算 `__pk` 字段（主键值数组的 JSON 字符串）作 Tabulator `index`，用于跨页勾选持久化；
- 勾选顺序用 `panel.selOrder` 数组自行维护（rowSelected 追加 / rowDeselected 移除），替换配对严格按此顺序；
- headerFilter 的 `like` 映射为后端 `contains`，其余映射 `eq`；数字类型列用 `=` 筛选。

- [ ] **Step 1: 写 browser.js 全部内容**

`databridge/web/static/js/browser.js`:

```javascript
// 数据浏览器：源/目标双网格，勾选行新增(追加)/替换(N对N按序)
(function () {
  const root = document.getElementById('tab-browser');
  root.innerHTML = `
    <div class="card" id="panel-src"><h3>源表</h3></div>
    <div class="card" style="text-align:center">
      <button class="btn" id="btn-insert">⬇ 新增到目标（追加，自增主键由目标分配）</button>
      <button class="btn red" id="btn-replace">⬇ 替换目标勾选行（N对N按勾选顺序）</button>
    </div>
    <div class="card" id="panel-dst"><h3>目标表</h3></div>`;

  // ---------- 面板：连接/库/表选择 + Tabulator 网格 ----------
  function createPanel(el, name) {
    const panel = { el, name, table: null, columns: [], pkCols: [],
                    selOrder: [], alias: '', db: '', tbl: '' };
    const bar = document.createElement('div');
    bar.className = 'grid-toolbar';
    bar.innerHTML = `
      <label>连接 <select class="sel-conn"><option value="">选择</option></select></label>
      <label>库 <select class="sel-db"></select></label>
      <label>表 <select class="sel-tbl"></select></label>
      <button class="btn gray b-load">加载</button>
      <span class="selinfo">已勾选 0 行</span>
      <button class="btn gray b-clear">清空勾选</button>`;
    el.appendChild(bar);
    const gridEl = document.createElement('div');
    el.appendChild(gridEl);
    panel.gridEl = gridEl;
    panel.bar = bar;

    loadConnections().then(list => {
      const sel = bar.querySelector('.sel-conn');
      list.forEach(c => sel.add(new Option(c.alias, c.alias)));
    });
    bar.querySelector('.sel-conn').onchange = async e => {
      panel.alias = e.target.value;
      const dbs = await api('GET', '/api/databases?alias=' + encodeURIComponent(panel.alias));
      const sel = bar.querySelector('.sel-db');
      sel.innerHTML = '';
      dbs.forEach(d => sel.add(new Option(d, d)));
      sel.onchange();
    };
    bar.querySelector('.sel-db').onchange = async () => {
      panel.db = bar.querySelector('.sel-db').value;
      if (!panel.db) return;
      const tbls = await api('GET', '/api/tables?alias=' +
        encodeURIComponent(panel.alias) + '&db=' + encodeURIComponent(panel.db));
      const sel = bar.querySelector('.sel-tbl');
      sel.innerHTML = '';
      tbls.forEach(t => sel.add(new Option(t, t)));
    };
    bar.querySelector('.b-load').onclick = () => loadGrid(panel);
    bar.querySelector('.b-clear').onclick = () => {
      panel.selOrder = [];
      if (panel.table) panel.table.deselectRow();
      updateSelInfo(panel);
    };
    return panel;
  }

  function updateSelInfo(panel) {
    panel.bar.querySelector('.selinfo').textContent =
      '已勾选 ' + panel.selOrder.length + ' 行';
  }

  // headerFilter 类型映射：字符串列 contains，其它 eq
  const NUMERIC = new Set(['int', 'bigint', 'smallint', 'tinyint', 'decimal',
                           'float', 'double', 'mediumint']);

  async function loadGrid(panel) {
    panel.tbl = panel.bar.querySelector('.sel-tbl').value;
    if (!panel.alias || !panel.db || !panel.tbl) { toast('请先选择连接/库/表', true); return; }
    // 先取第一页拿列元数据
    const first = await api('POST', '/api/browse', {
      alias: panel.alias, db: panel.db, table: panel.tbl, page: 1, page_size: 50 });
    panel.columns = first.columns;
    panel.pkCols = first.columns.filter(c => c.is_pk).map(c => c.name);
    if (!panel.pkCols.length) { toast('该表无主键，不支持勾选同步', true); return; }
    panel.selOrder = [];
    updateSelInfo(panel);

    const colDefs = [{ formatter: 'rowSelection', titleFormatter: 'rowSelection',
                       hozAlign: 'center', headerSort: false, width: 44 }];
    panel.columns.forEach(c => colDefs.push({
      title: c.name + (c.is_pk ? ' 🔑' : ''), field: c.name,
      headerFilter: 'input',
      headerFilterFunc: NUMERIC.has(c.type) ? '=' : 'like',
    }));

    if (panel.table) panel.table.destroy();
    panel.table = new Tabulator(panel.gridEl, {
      height: 320, layout: 'fitDataStretch', index: '__pk',
      selectableRows: true, selectableRowsPersistence: true,
      pagination: true, paginationMode: 'remote', paginationSize: 50,
      paginationSizeSelector: [20, 50, 100],
      sortMode: 'remote', filterMode: 'remote',
      ajaxURL: '/api/browse',   // 占位，实际请求由 ajaxRequestFunc 发出
      ajaxRequestFunc: async (url, config, params) => {
        const filters = (params.filter || []).map(f => ({
          column: f.field,
          op: f.type === 'like' ? 'contains' : 'eq',
          value: f.value,
        }));
        const sort = (params.sort || [])[0];
        const out = await api('POST', '/api/browse', {
          alias: panel.alias, db: panel.db, table: panel.tbl,
          page: params.page || 1, page_size: params.size || 50,
          filters, sort_column: sort ? sort.field : null,
          sort_dir: sort ? sort.dir : 'asc',
        });
        out.rows.forEach(r => {
          r.__pk = JSON.stringify(panel.pkCols.map(k => r[k]));
        });
        return { last_page: Math.max(1, Math.ceil(out.total / (params.size || 50))),
                 data: out.rows };
      },
      columns: colDefs,
    });
    panel.table.on('rowSelected', row => {
      const pk = row.getIndex();
      if (!panel.selOrder.includes(pk)) panel.selOrder.push(pk);
      updateSelInfo(panel);
    });
    panel.table.on('rowDeselected', row => {
      panel.selOrder = panel.selOrder.filter(k => k !== row.getIndex());
      updateSelInfo(panel);
    });
  }

  const src = createPanel(document.getElementById('panel-src'), '源');
  const dst = createPanel(document.getElementById('panel-dst'), '目标');

  function ref(panel) {
    return { alias: panel.alias, db: panel.db, table: panel.tbl };
  }
  function pkValues(panel) {
    return panel.selOrder.map(s => JSON.parse(s));
  }
  async function isProtected(alias) {
    const list = await loadConnections();
    const c = list.find(x => x.alias === alias);
    return c ? c.protected : false;
  }
  function ready(panel) {
    if (!panel.table) { toast(panel.name + '表未加载', true); return false; }
    return true;
  }

  // ---------- 新增（追加） ----------
  document.getElementById('btn-insert').onclick = async () => {
    if (!ready(src) || !ready(dst)) return;
    if (!src.selOrder.length) { toast('请先在源表勾选行', true); return; }
    const prot = await isProtected(dst.alias);
    const ok = await showConfirm(
      `将源表勾选的 <b>${src.selOrder.length}</b> 行追加到目标
       <b>${dst.alias} / ${dst.db} / ${dst.tbl}</b><br>
       自增主键由目标表自动分配。`, { requireProtected: prot });
    if (!ok) return;
    const out = await api('POST', '/api/rows/insert', {
      src: ref(src), dst: ref(dst), pk_values: pkValues(src), confirm: true });
    toast('新增成功：' + out.inserted + ' 行');
    dst.table.setData();   // 刷新目标网格
  };

  // ---------- 替换（N对N按序） ----------
  document.getElementById('btn-replace').onclick = async () => {
    if (!ready(src) || !ready(dst)) return;
    if (src.selOrder.length === 0 || src.selOrder.length !== dst.selOrder.length) {
      toast(`源已勾 ${src.selOrder.length} 行 / 目标已勾 ${dst.selOrder.length} 行，数量必须相等且大于 0`, true);
      return;
    }
    // 配对预览表：源第 i 个勾选 -> 目标第 i 个勾选
    const pairs = src.selOrder.map((s, i) =>
      `<tr><td>${s}</td><td>→</td><td>${dst.selOrder[i]}</td></tr>`).join('');
    const prot = await isProtected(dst.alias);
    const ok = await showConfirm(
      `替换目标 <b>${dst.alias} / ${dst.db} / ${dst.tbl}</b> 的
       <b>${dst.selOrder.length}</b> 行（目标主键保留，其余列被源行覆盖）：
       <table class="plain"><tr><th>源主键</th><th></th><th>目标主键</th></tr>${pairs}</table>`,
      { requireProtected: prot });
    if (!ok) return;
    const out = await api('POST', '/api/rows/replace', {
      src: ref(src), dst: ref(dst),
      src_pk_values: pkValues(src), dst_pk_values: pkValues(dst), confirm: true });
    toast('替换成功：' + out.replaced + ' 行');
    dst.table.setData();
  };
})();
```

注意：前端永远传 `confirm: true` 是因为 GUI 已用确认框（含受保护复选框）完成了交互确认；server 侧护栏对 MCP 等其它调用方仍然生效。

- [ ] **Step 2: 手工验证（需本地 MySQL 两个库/表）**

Run: `uv run uvicorn databridge.web.app:app --port 8000`

验证清单：
1. 源/目标面板各自选择连接→库→表，点「加载」后网格渲染、分页可用；
2. 列头输入筛选值后列表变化（服务端筛选）；点列头排序生效；
3. 第 1 页勾 2 行、翻到第 2 页再勾 1 行，回第 1 页勾选仍在，「已勾选 3 行」；
4. 新增：源勾 2 行点「新增到目标」，确认后目标表多 2 行且主键是新自增值；
5. 替换：源勾 2 行、目标勾 2 行，确认框展示配对表，执行后目标行内容被覆盖但主键不变；
6. 数量不等（源 2 目标 1）时 toast 拒绝；
7. 目标选受保护连接时，确认框出现红色复选框，不勾无法确认；
8. 列结构不同的两张表执行新增，toast 展示差异列中文提示。

- [ ] **Step 3: Commit**

```bash
git add databridge/web/static/js/browser.js
git commit -m "feat: 数据浏览器双网格 + 勾选行新增/替换"
```

---

### Task 12: 整表同步页 + README 收尾

**Files:**
- Modify: `databridge/web/static/js/sync.js`（Task 10 建的空文件，写入全部内容）
- Create: `README.md`

**Interfaces:**
- Consumes: `api/toast/showConfirm/loadConnections`（Task 10）、`POST /api/sync/preview`、`POST /api/sync/execute`（Task 9）
- Produces: 整表同步页（选源/目标 + 可选 WHERE → 预览 → 执行 → 结果统计）；项目 README

- [ ] **Step 1: 写 sync.js**

`databridge/web/static/js/sync.js`:

```javascript
// 整表增量同步页：预览（dry-run）→ 执行（upsert）
(function () {
  const root = document.getElementById('tab-sync');
  root.innerHTML = `
    <div class="card">
      <h3>整表增量同步（按主键比对，新增+覆盖，不删除）</h3>
      <div class="grid-toolbar" id="s-src"><b>源：</b></div>
      <div class="grid-toolbar" id="s-dst"><b>目标：</b></div>
      <div class="grid-toolbar">
        <label>WHERE（可选，仅限定源表范围） <input id="s-where" style="width:320px"
          placeholder="如 id > 100 AND status = 'A'"></label>
      </div>
      <button class="btn gray" id="s-preview">预览差异（不写数据）</button>
      <button class="btn" id="s-exec">执行同步</button>
      <div class="card" id="s-result" style="display:none"></div>
    </div>`;

  // 一行连接/库/表选择器
  function selector(el) {
    const s = { alias: '', db: '', tbl: '' };
    el.insertAdjacentHTML('beforeend', `
      <label>连接 <select class="q-conn"><option value="">选择</option></select></label>
      <label>库 <select class="q-db"></select></label>
      <label>表 <select class="q-tbl"></select></label>`);
    loadConnections().then(list => {
      const sel = el.querySelector('.q-conn');
      list.forEach(c => sel.add(new Option(c.alias, c.alias)));
    });
    el.querySelector('.q-conn').onchange = async e => {
      s.alias = e.target.value;
      const dbs = await api('GET', '/api/databases?alias=' + encodeURIComponent(s.alias));
      const sel = el.querySelector('.q-db');
      sel.innerHTML = '';
      dbs.forEach(d => sel.add(new Option(d, d)));
      sel.onchange();
    };
    el.querySelector('.q-db').onchange = async () => {
      s.db = el.querySelector('.q-db').value;
      if (!s.db) return;
      const tbls = await api('GET', '/api/tables?alias=' +
        encodeURIComponent(s.alias) + '&db=' + encodeURIComponent(s.db));
      const sel = el.querySelector('.q-tbl');
      sel.innerHTML = '';
      tbls.forEach(t => sel.add(new Option(t, t)));
    };
    s.read = () => { s.tbl = el.querySelector('.q-tbl').value; return s; };
    return s;
  }

  const src = selector(document.getElementById('s-src'));
  const dst = selector(document.getElementById('s-dst'));

  function body() {
    src.read(); dst.read();
    if (!src.alias || !src.db || !src.tbl || !dst.alias || !dst.db || !dst.tbl) {
      toast('请选择完整的源/目标 连接/库/表', true);
      return null;
    }
    return {
      src: { alias: src.alias, db: src.db, table: src.tbl },
      dst: { alias: dst.alias, db: dst.db, table: dst.tbl },
      where: document.getElementById('s-where').value.trim() || null,
    };
  }

  function showResult(html) {
    const el = document.getElementById('s-result');
    el.style.display = 'block';
    el.innerHTML = html;
  }

  document.getElementById('s-preview').onclick = async () => {
    const b = body();
    if (!b) return;
    const out = await api('POST', '/api/sync/preview', b);
    showResult(`<b>预览结果（未写入任何数据）</b><br>
      将新增：${out.to_insert} 行，将覆盖：${out.to_update} 行<br>
      主键示例：${JSON.stringify(out.sample_pks)}`);
  };

  document.getElementById('s-exec').onclick = async () => {
    const b = body();
    if (!b) return;
    const list = await loadConnections();
    const prot = (list.find(c => c.alias === b.dst.alias) || {}).protected;
    const ok = await showConfirm(
      `将 <b>${b.src.alias}/${b.src.db}/${b.src.table}</b> 增量同步到
       <b>${b.dst.alias}/${b.dst.db}/${b.dst.table}</b><br>
       冲突策略：同主键覆盖（upsert）；不删除目标多余行。`,
      { requireProtected: !!prot });
    if (!ok) return;
    const t0 = Date.now();
    const out = await api('POST', '/api/sync/execute', Object.assign({ confirm: true }, b));
    showResult(`<b>同步完成</b><br>
      新增：${out.inserted} 行，覆盖：${out.updated} 行，
      耗时：${((Date.now() - t0) / 1000).toFixed(1)}s`);
    toast('同步完成');
  };
})();
```

- [ ] **Step 2: 写 README.md**

```markdown
# DataBridge — MySQL 表数据同步工具

一套同步引擎，两副面孔（本迭代交付 Web GUI，MCP 入口下迭代接入）。

## 功能

- **连接管理**：增删改查 / 测试连接 / 受保护标记；密码 Fernet 加密存本地 `data/`（不进 git）
- **数据浏览器**：源/目标双网格，列筛选+排序+分页+跨页勾选；
  勾选行**新增**（去自增主键追加）或 **N对N替换**（按勾选顺序配对，保留目标主键）
- **整表增量同步**：主键逐行比对，预览（dry-run）→ upsert 执行；不删除、不动 DDL
- **安全护栏**：写入受保护连接必须显式确认；密码永不回显/入日志

## 运行

```bash
uv sync
uv run uvicorn databridge.web.app:app --port 8000
# 浏览器打开 http://127.0.0.1:8000/
```

## 测试

```bash
uv run pytest -v
```

## 目录结构

- `databridge/engine/` 同步引擎（纯逻辑，无 Web 依赖，未来 MCP 直接复用）
- `databridge/storage/` 连接配置加密存储
- `databridge/service.py` 护栏 + 用例编排（入口层共用）
- `databridge/web/` FastAPI + 静态前端

设计文档：`docs/superpowers/specs/2026-07-29-databridge-web-sync-design.md`
```

- [ ] **Step 3: 全量回归 + 手工验收**

Run: `uv run pytest -v`
Expected: 全部通过（约 30+ 用例）

Run: `uv run uvicorn databridge.web.app:app --port 8000`，按 spec §10 验收清单逐项手工验证：
1. 整表同步页：预览返回新增/覆盖行数（此时目标表未变）；执行后数据落库、结果统计展示；
2. 目标表不存在时报中文错误；主键结构不一致时报 primary_key_mismatch；
3. 受保护连接未确认时三类写操作均被拒绝（可用 curl 不带 confirm 验证 403）。

- [ ] **Step 4: Commit**

```bash
git add databridge/web/static/js/sync.js README.md
git commit -m "feat: 整表同步页 + README"
```

---

## 任务依赖关系

```
Task 1 (脚手架)
  └─ Task 2 (errors + storage)
       ├─ Task 3 (测试桩 + connection)
       │    ├─ Task 4 (inspector)
       │    │    ├─ Task 5 (browser)
       │    │    └─ Task 6 (writer)
       │    │         └─ Task 7 (diff)
       │    └─ Task 8 (service，依赖 4-7)
       └─ Task 9 (Web API，依赖 8)
            └─ Task 10 (前端骨架+连接页)
                 ├─ Task 11 (数据浏览器+勾选同步)
                 └─ Task 12 (整表同步页+README)
```

## 验收对照（spec §10）

| 验收项 | 对应任务 |
|--------|----------|
| 1 连接管理 | Task 2, 9, 10 |
| 2 数据浏览器 | Task 5, 9, 11 |
| 3 勾选新增 | Task 6, 8, 9, 11 |
| 4 勾选替换 | Task 6, 8, 9, 11 |
| 5 整表同步 | Task 7, 8, 9, 12 |
| 6 护栏 | Task 8, 9（403 测试）, 10（确认框） |
| 7 单测全绿 | Task 2-9 各自的测试 + Task 12 全量回归 |
