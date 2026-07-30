# DataBridge MCP HTTP 传输与容器化 设计

日期：2026-07-30
状态：关键决策已与需求方确认（① Streamable HTTP ② docker-compose 两服务共享 data 卷
③ 保留 stdio 默认、环境变量切 HTTP；两硬点认可）
需求来源：`mysql-sync-requirements.md` §8（下个迭代：常驻容器 + HTTP 传输，引擎与传输解耦）

## 1. 目标

在不改动同步引擎的前提下，为 MCP server 增加 HTTP 传输入口并容器化：
- 现有 stdio 入口保持默认不变（当前 MySmallAgent 不受影响）；
- 通过环境变量切到 Streamable HTTP，以常驻容器方式提供服务；
- Web GUI 与 MCP 各自容器化，共享同一份加密连接存储。

## 2. 传输入口（`mcp_server.py` 重构）

单入口两用，由环境变量选择传输；引擎与工具层零改动。已验证 FastMCP 1.29.0
`mcp.settings` 在构造后可改 host/port/stateless_http/json_response，`run(transport=...)`
运行时读取。

```python
import os
from databridge.mcp.server import create_mcp

def build(env=None):
    """按环境变量构建并配置好 (mcp, transport)；默认 stdio。"""
    env = env if env is not None else os.environ
    transport = env.get("MCP_TRANSPORT", "stdio")
    mcp = create_mcp()
    if transport != "stdio":
        mcp.settings.host = env.get("MCP_HOST", "0.0.0.0")
        mcp.settings.port = int(env.get("MCP_PORT", "8100"))
        mcp.settings.stateless_http = True
        mcp.settings.json_response = True
    return mcp, transport

def main():
    mcp, transport = build()
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()
```

环境变量：
- `MCP_TRANSPORT`：`stdio`（默认）| `streamable-http` | `sse`
- `MCP_HOST`：HTTP 绑定地址，默认 `0.0.0.0`（容器外可达）
- `MCP_PORT`：HTTP 端口，默认 `8100`（避开 Web 的 8000）

硬点：HTTP 模式固定 `stateless_http=True` + `json_response=True`（无状态，契合原
"连接→调用→退出"哲学，利于横向扩展）。`create_mcp` 签名不变，既有测试全部不受影响。

## 3. 容器拓扑（docker-compose 两服务共享卷）

一个 `Dockerfile`（同一镜像含全部代码），`docker-compose.yml` 起两个服务、
共享一个命名卷 `databridge-data` 挂到 `/app/data`：

- `web`：`uvicorn databridge.web.app:app --host 0.0.0.0 --port 8000`，映射 8000；
- `mcp`：`python mcp_server.py`，环境变量 `MCP_TRANSPORT=streamable-http`，映射 8100。

在 web 里添加连接 → 落盘到共享卷 → mcp 侧同一份 `connections.json`/`.key` 可读。

**硬点：`data/` 必须挂卷持久化**。否则容器重启后连接丢失，且 `.key` 重新生成会使
已存密码永久无法解密。命名卷保证两服务共享且重启不丢。

### Dockerfile 要点
- 基础镜像 `python:3.11-slim`；`pip install uv`；
- 先 `COPY pyproject.toml uv.lock` 再 `uv sync --frozen --no-dev`（利用层缓存、不装 dev 依赖）；
- 再 `COPY databridge/ ./databridge/` 与 `COPY mcp_server.py ./`（含 web 静态资源）；
- `EXPOSE 8100`；默认 `CMD` 起 mcp（compose 中 web 服务覆盖 command）；
- 不拷 `data/`（含密钥、gitignore）；配 `.dockerignore` 排除 `data/`、`.venv/`、`.git/`、
  `.pytest_tmp/`、`.superpowers/`、`__pycache__/`。

## 4. 测试计划

不启动真实 HTTP 服务、不连真实 MySQL；只在进程内验证入口的传输配置逻辑
（`import mcp_server` 已有先例）。新增 `tests/test_mcp_entry.py`：

1. 默认 stdio：`build({})` 返回 transport == `"stdio"`；
2. HTTP 配置：`build({"MCP_TRANSPORT": "streamable-http", "MCP_PORT": "9000"})` 返回
   transport == `"streamable-http"`，且 `mcp.settings.host == "0.0.0.0"`、`port == 9000`、
   `stateless_http is True`、`json_response is True`；
3. 6 个工具仍齐全（`build` 得到的 mcp 复用既有 `_tool_names` 断言，防重构漏工具）。

Docker 层不写自动化测试（无 Docker-in-test 环境）；人工验证见 §5。

## 5. 人工验证（实施收尾）

- `docker compose up --build` 起两服务；浏览器 `http://localhost:8000/` 加一条连接；
- agent 侧 HTTP 配置指向 `http://localhost:8100/mcp`，确认 `/tools` 出现 6 个工具、
  `list_connections` 返回不含密码；
- 重启 compose，确认连接仍在（卷持久化生效）。

## 6. 文档

README 增补「HTTP / Docker 部署」小节：compose 起停、环境变量说明、
agent 侧 HTTP `mcp.json` 示例（`{"mcpServers":{"mysql-sync":{"url":"http://localhost:8100/mcp"}}}`，
具体键名以 agent 客户端为准）。

## 7. 假设与既定决策

- 传输默认 stdio 不变，HTTP 经环境变量开启：保证当前 agent 零改动仍可用。
- 传输类型 = Streamable HTTP（`/mcp` 端点）；SSE 仅 SDK 顺带支持，不主推。
- 两服务共享命名卷是连接可被 MCP 读到的前提（连接只能在 Web GUI 添加，§3-4）。
- 引擎/服务/工具层零改动，仅新增入口逻辑 + 部署文件（§8 解耦要求）。
