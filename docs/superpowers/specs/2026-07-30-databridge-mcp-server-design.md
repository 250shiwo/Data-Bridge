# DataBridge MCP stdio server 设计

日期：2026-07-30
状态：已与需求方逐节确认
需求来源：`mysql-sync-requirements.md` §2、§4、§5（接入契约不可偏离）

## 1. 目标

为 DataBridge 增加第二副面孔：MCP stdio server，供 MySmallAgent 以子进程方式拉起调用，
实现"QQ → agent → MCP → 同步完成"链路。复用现有 `SyncService`，引擎与 Web 层零改动。

## 2. 架构与文件布局

```
DataBridge/
├── mcp_server.py              # 新增：启动壳（文档契约固定的入口路径）
├── databridge/
│   └── mcp/                   # 新增：MCP 薄壳层，与 web/ 对称
│       ├── __init__.py
│       └── server.py          # create_mcp(data_dir) 工厂 + 5 个工具定义
└── tests/
    └── test_mcp_server.py     # 新增：工具函数级测试
```

- `databridge/mcp/server.py`：提供 `create_mcp(data_dir: Path | None = None) -> FastMCP`
  工厂函数，内部构建 `ConnectionStore(data_dir or Path("data"))` + `SyncService`，
  与 `web/app.py` 的 `create_app` 完全同构；`data_dir` 可注入临时目录供测试。
- `mcp_server.py`（根目录）：仅 `from databridge.mcp.server import create_mcp` +
  `create_mcp().run()`。stdio 传输是 FastMCP 默认，符合"启动快、无状态、用完即退"。
- 依赖：`pyproject.toml` 新增官方 SDK `mcp>=1.0`（含 FastMCP）。
- 不改动 engine / service / storage / web；护栏复用 service 层 `_guard_write`。
- 演进：未来 HTTP 传输只需换 `mcp.run()` 的 transport 参数，引擎不动（需求 §8）。

## 3. 工具定义（共 5 个）

参数一律扁平化（不用嵌套对象，对 LLM 更友好）；描述全中文，原样展示给 LLM。

| 工具 | 参数 | 返回 |
|------|------|------|
| `list_connections` | 无 | `[{alias, host, port, user, default_db, protected}]`（`store.list_safe()`，永不含密码） |
| `list_databases` | `alias` | `["db1", ...]` |
| `list_tables` | `alias, db` | `["t1", ...]` |
| `preview_sync` | `src_alias, src_db, src_table, dst_alias, dst_db, dst_table, where=None` | `{to_insert, to_update, sample_pks}` |
| `execute_sync` | 同 preview_sync + `confirm=False` | `{inserted, updated}` |

描述文案要点（写进 docstring，本身是护栏的一部分）：

- `preview_sync`：dry-run 比对，只统计将新增/覆盖的行数与主键示例，不写任何数据。
  **执行同步前必须先调用本工具，把结果汇报给用户确认**。
- `execute_sync`：真正执行增量同步（新增 + upsert 覆盖，不删除行）。
  **调用前必须先用 preview_sync 预览并经用户确认**。
  目标为受保护连接时必须传 `confirm=true`，否则拒绝。
- `list_connections`：列出已配置的连接别名及基本信息（不含凭据）。
  其他工具参数中的 alias 必须来自这里。

工具内部实现均为 1-3 行转发：扁平参数组装成 `{"alias", "db", "table"}` 字典后调
`SyncService` 对应方法。MCP 层不重复实现任何护栏判定。

边界：MCP 面孔不提供连接的增删改/测试（需求 §3-4），连接只能在 Web GUI 管理；
本迭代不提供 browse_table 等浏览类工具。

## 4. 错误处理与凭据安全

MCP 无 HTTP 状态码，错误经工具调用的 `isError` + 文本消息传给 LLM。
`_safe` 装饰器统一包住 5 个工具（对应 web 层两个 exception_handler）：

- 业务错误（`DataBridgeError` 及子类）→ 重抛为 `[错误码] 中文提示`，如
  `[protected_connection] 连接 prod 为受保护连接，写入必须显式确认（confirm=true）`，
  LLM 可据此自行纠正（补 confirm、换别名等）。
- 未知异常（如 pymysql 网络错误）→ 不回显异常原文，只抛 `服务内部错误：{异常类名}`，
  避免驱动异常文本夹带主机/账号信息进入对话上下文。

凭据安全：

1. 工具参数、返回值全程只有别名；密码仅在 service→engine 内部流转（现有机制）。
2. `list_connections` 复用 `list_safe()`，物理上不可能带出密码。
3. stdio 纪律：stdout 是 JSON-RPC 信道，MCP 层禁止任何 `print`；日志一律走 stderr
  （FastMCP 默认）。实施时检查引擎调用路径无杂散 stdout 输出。

## 5. 测试计划

新增 `tests/test_mcp_server.py`，沿用现有风格（`tmp_path` 注入 + conftest 的
FakeConnection），不依赖真实 MySQL、不起 stdio 进程——`create_mcp(data_dir=tmp_path)`
后经 FastMCP 进程内调用接口调工具：

1. 工具注册完整性：5 个工具存在，名称与参数 schema 符合本设计；
2. `list_connections` 脱敏：存入带密码连接后，返回全文不含密码；
3. 护栏拒绝：受保护目标 + `confirm=False` 时 `execute_sync` 报错，消息含
   `protected_connection` 与中文提示；`confirm=True` 时放行（注入 fake connect）；
4. 业务错误转换：不存在的别名 → 错误消息含 `[connection_not_found]`；
5. 未知异常掩蔽：注入抛 RuntimeError 的 connect，断言错误文本仅含异常类名；
6. preview/execute 正常路径：FakeConnection 预置结果集，断言返回结构
   `{to_insert, to_update, sample_pks}` / `{inserted, updated}`。

人工验证（实施收尾，不写自动化）：

- 本机 `uv run python mcp_server.py` 配入一个 MCP client 冒烟，确认出现 5 个工具
 （对应需求验收标准 2）；
- README 增补 MCP 接入说明与 `mcp.json` 示例。

## 6. 假设与既定决策

- 传输方式 stdio、入口 `mcp_server.py`、FastMCP SDK：需求 §2 契约锁定，不可变。
- 工具清单 = 需求 §4 四工具 + `list_databases`：需求方已确认。
- agent 侧自动批准一切调用，所有护栏必须在本项目 server 侧实现（需求 §5）。
