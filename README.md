# DataBridge — MySQL 表数据同步工具

一套同步引擎，两副面孔（Web GUI + MCP stdio server）。

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

- `databridge/engine/` 同步引擎（纯逻辑，无 Web 依赖，Web 与 MCP 入口共用）
- `databridge/storage/` 连接配置加密存储
- `databridge/service.py` 护栏 + 用例编排（入口层共用）
- `databridge/web/` FastAPI + 静态前端

设计文档：`docs/superpowers/specs/2026-07-29-databridge-web-sync-design.md`

## MCP 接入（stdio）

本项目同时是一个 MCP stdio server，暴露 6 个工具：
`list_connections`、`list_databases`、`list_tables`、`browse_table`、`preview_sync`、`execute_sync`。

agent 侧 `mcp.json` 配置示例（`<本项目绝对路径>` 替换为实际路径）：

```json
{
  "mcpServers": {
    "mysql-sync": {
      "command": "uv",
      "args": ["--directory", "<本项目绝对路径>", "run", "python", "mcp_server.py"]
    }
  }
}
```

说明：

- 连接只能在 Web GUI 中添加/编辑，MCP 工具一律按别名引用，凭据永不出现在参数或返回值中；
- 向受保护连接写入时 `execute_sync` 必须显式携带 `confirm=true`，否则拒绝；
- 推荐流程：先 `preview_sync` 预览差异并向用户汇报，确认后再 `execute_sync`。

## HTTP / Docker 部署

除 stdio 外，MCP server 支持 Streamable HTTP，可容器化常驻。

一键起两服务（web 加连接、mcp 供 agent 调用，共享加密连接卷）：

```bash
docker compose up --build
# Web GUI:  http://localhost:8000/
# MCP HTTP: http://localhost:8100/mcp
```

环境变量（作用于 `mcp_server.py`）：

- `MCP_TRANSPORT`：`stdio`（默认）/ `streamable-http` / `sse`
- `MCP_HOST`：HTTP 绑定地址，默认 `0.0.0.0`
- `MCP_PORT`：HTTP 端口，默认 `8100`

agent 侧 HTTP 接入（把 stdio 条目换成 url 即可；键名以 agent 客户端为准）：

```json
{
  "mcpServers": {
    "mysql-sync": { "url": "http://<host>:8100/mcp" }
  }
}
```

注意：

- `data/`（`connections.json` + 密钥 `.key`）经命名卷 `databridge-data` 持久化，勿删卷、勿丢 `.key`（否则已存密码无法解密）；
- `/mcp` 端点无鉴权，勿暴露公网——compose 默认只在本机回环映射 `127.0.0.1:8100`，agent 与 mcp 应走同一内网/docker 网络。
