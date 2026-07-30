# DataBridge MCP HTTP 传输与容器化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `mcp_server.py` 单入口两用（默认 stdio、环境变量切 Streamable HTTP），并用 Dockerfile + docker-compose 把 Web GUI 与 MCP HTTP 两服务容器化、共享加密连接卷。

**Architecture:** 入口新增 `build(env)` 依 `MCP_TRANSPORT` 选传输并配置 FastMCP settings；`create_mcp` 与工具/引擎层零改动。部署侧新增单 `Dockerfile`（同镜像含全部代码）+ `docker-compose.yml`（web:8000 / mcp:8100 共享命名卷 `databridge-data:/app/data`）+ `.dockerignore`。

**Tech Stack:** Python 3.11+、uv、mcp 1.29.0（FastMCP，`run(transport="streamable-http")`）、Docker / docker-compose、pytest（进程内验证配置逻辑，不起真实 HTTP 服务、不连真实 MySQL）。

**Spec:** `docs/superpowers/specs/2026-07-30-databridge-mcp-http-docker-design.md`

## Global Constraints

- 传输默认 `stdio`（当前 MySmallAgent 的 stdio 配置零破坏）；`MCP_TRANSPORT=streamable-http` 切 HTTP。
- 环境变量：`MCP_TRANSPORT`（stdio 默认 / streamable-http / sse）、`MCP_HOST`（默认 `0.0.0.0`）、`MCP_PORT`（默认 `8100`）。
- HTTP 模式固定 `stateless_http=True` + `json_response=True`；端点路径保持 FastMCP 默认 `/mcp`（不改）。
- `create_mcp(data_dir=None, connect=open_connection)` 签名不变；引擎/服务/工具层零改动；既有 12 个 MCP 测试与全量套件必须保持全绿。
- `data/` 必须挂命名卷持久化（连接 + `.key`）；MCP 端口不暴露公网（仅内网/可信网段）。
- Docker 不拷 `data/`；`.dockerignore` 排除 `data/`、`.venv/`、`.git/`、`.pytest_tmp/`、`.superpowers/`、`__pycache__/`。
- 代码注释/文档用中文；每个任务收尾运行 `uv run pytest -q` 保证全量绿。

---

### Task 1: 入口双模重构（`build(env)` + `main`）

**Files:**
- Modify: `mcp_server.py`（重写为 `build` + `main`，保留 stdio 默认行为）
- Test: `tests/test_mcp_entry.py`（新建）

**Interfaces:**
- Consumes: `databridge.mcp.server.create_mcp`（现有，签名不变）；测试复用现有 `tests/test_mcp_server.py` 里的 `_tool_names` 无法跨文件直接 import，故本任务测试自带一个等价内联断言（见 Step 1）。
- Produces: `mcp_server.build(env: dict | None = None) -> tuple[FastMCP, str]`（返回配置好的 mcp 与 transport 名）；`mcp_server.main() -> None`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_mcp_entry.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_mcp_entry.py -v`
Expected: FAIL —— `AttributeError: module 'mcp_server' has no attribute 'build'`（当前入口只有 `create_mcp().run()`）。

- [ ] **Step 3: 重写入口实现**

把 `mcp_server.py` 整体替换为：

```python
"""MCP 入口：默认 stdio（agent 子进程拉起）；设 MCP_TRANSPORT=streamable-http 时以 HTTP 常驻（容器用）。

环境变量：
  MCP_TRANSPORT  stdio(默认) | streamable-http | sse
  MCP_HOST       HTTP 绑定地址，默认 0.0.0.0
  MCP_PORT       HTTP 端口，默认 8100
"""
import os

from databridge.mcp.server import create_mcp


def build(env=None):
    """按环境变量构建并配置好 (mcp, transport)；默认 stdio，引擎与工具层零改动。"""
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

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_mcp_entry.py -v`
Expected: 3 passed。

- [ ] **Step 5: 验证 stdio 入口仍可正常导入拉起（不阻塞）**

Run: `uv run python -c "import mcp_server; print('entry ok')"`
Expected: 输出 `entry ok` 且立即退出（`__main__` 保护生效）。

- [ ] **Step 6: 全量回归 + 提交**

```powershell
uv run pytest -q
git add mcp_server.py tests/test_mcp_entry.py
git commit -m "feat: MCP 入口双模（stdio 默认 + 环境变量切 streamable-http）"
```

Expected: 全量通过（原 53 + 新 3 = 56 passed）。

---

### Task 2: 容器化（Dockerfile + .dockerignore + docker-compose.yml）

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: Task 1 的 `mcp_server.py`（`MCP_TRANSPORT` 等环境变量）；现有 `databridge.web.app:app`（uvicorn 入口）。
- Produces: 可 `docker compose up --build` 起的 `web`(8000) 与 `mcp`(8100) 两服务，共享命名卷 `databridge-data`。

- [ ] **Step 1: 创建 `.dockerignore`**

创建 `.dockerignore`：

```
data/
.venv/
.git/
.gitignore
.pytest_cache/
.pytest_tmp/
.superpowers/
**/__pycache__/
*.pyc
docs/
tests/
```

- [ ] **Step 2: 创建 `Dockerfile`**

创建 `Dockerfile`：

```dockerfile
# DataBridge 统一镜像：同一份代码，compose 中按服务分别以 web / mcp 启动。
FROM python:3.11-slim

# uv 负责依赖解析与运行
RUN pip install --no-cache-dir uv

WORKDIR /app

# 先拷依赖清单并锁定安装（不装 dev 依赖），利用镜像层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 再拷源码（含 databridge/web/static 前端资源）与入口
COPY databridge/ ./databridge/
COPY mcp_server.py ./

# 连接与密钥持久化目录（compose 挂命名卷到此）
VOLUME ["/app/data"]

# 默认以 MCP HTTP 常驻启动；compose 中 web 服务覆盖 command
EXPOSE 8100
ENV MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8100
CMD ["uv", "run", "python", "mcp_server.py"]
```

- [ ] **Step 3: 创建 `docker-compose.yml`**

创建 `docker-compose.yml`：

```yaml
# 两副面孔：web 加连接、mcp 供 agent 调用，共享同一份加密连接卷。
services:
  web:
    build: .
    command: uv run uvicorn databridge.web.app:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    volumes:
      - databridge-data:/app/data

  mcp:
    build: .
    environment:
      MCP_TRANSPORT: streamable-http
      MCP_HOST: 0.0.0.0
      MCP_PORT: "8100"
    # 安全：MCP 端点无鉴权，仅在可信网段/内网映射，勿暴露公网
    ports:
      - "127.0.0.1:8100:8100"
    volumes:
      - databridge-data:/app/data

volumes:
  databridge-data:
```

- [ ] **Step 4: 校验 compose 文件语法**

Run: `docker compose config`
Expected: 打印解析后的规范化配置、无报错（若本机无 docker，则跳过并在报告中注明"待人工用 docker compose config 校验"）。

- [ ] **Step 5: 校验 Dockerfile 构建（可选，视本机 docker 可用性）**

Run: `docker build -t databridge:test .`
Expected: 构建成功至末层。若本机无 docker 或网络受限拉不到基础镜像，则跳过并在报告中明确标注"未构建、留待人工验证"，不得谎报成功。

- [ ] **Step 6: 全量回归 + 提交**

```powershell
uv run pytest -q
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "feat: 容器化 Web+MCP 双服务，共享 data 命名卷"
```

Expected: pytest 全量仍绿（Docker 文件不影响测试），提交成功。

---

### Task 3: README 补「HTTP / Docker 部署」小节

**Files:**
- Modify: `README.md`（末尾追加一节）

**Interfaces:**
- Consumes: Task 1/2 的环境变量与 compose 服务名、端口。
- Produces: 无代码接口，仅文档。

- [ ] **Step 1: 追加部署章节**

在 `README.md` 末尾追加（紧接现有「## MCP 接入（stdio）」小节之后）：

```markdown
## HTTP / Docker 部署

除 stdio 外，MCP server 支持 Streamable HTTP，可容器化常驻。

一键起两服务（web 加连接、mcp 供 agent 调用，共享加密连接卷）：

​```bash
docker compose up --build
# Web GUI:  http://localhost:8000/
# MCP HTTP: http://localhost:8100/mcp
​```

环境变量（作用于 `mcp_server.py`）：

- `MCP_TRANSPORT`：`stdio`（默认）/ `streamable-http` / `sse`
- `MCP_HOST`：HTTP 绑定地址，默认 `0.0.0.0`
- `MCP_PORT`：HTTP 端口，默认 `8100`

agent 侧 HTTP 接入（把 stdio 条目换成 url 即可；键名以 agent 客户端为准）：

​```json
{
  "mcpServers": {
    "mysql-sync": { "url": "http://<host>:8100/mcp" }
  }
}
​```

注意：

- `data/`（`connections.json` + 密钥 `.key`）经命名卷 `databridge-data` 持久化，勿删卷、勿丢 `.key`（否则已存密码无法解密）；
- `/mcp` 端点无鉴权，勿暴露公网——compose 默认只在本机回环映射 `127.0.0.1:8100`，agent 与 mcp 应走同一内网/docker 网络。
```

（写入 README 时把上面代码块内 ​``` 前的零宽转义去掉，保证是合法嵌套代码块。）

- [ ] **Step 2: 通读校验**

打开 `README.md`，确认新章节的三个代码块（bash、json、bash）围栏成对、无零宽字符残留、渲染正常。

- [ ] **Step 3: 提交**

```powershell
git add README.md
git commit -m "docs: README 增补 HTTP/Docker 部署说明"
```

---

## 人工验证（实施收尾，不写自动化）

- `docker compose up --build` 起两服务；浏览器 `http://localhost:8000/` 加一条连接；
- agent 侧 HTTP 条目指向 `http://localhost:8100/mcp`，确认 `/tools` 出现 6 个工具、`list_connections` 不含密码；
- `docker compose down` 后再 `up`，确认连接仍在（命名卷持久化生效）。
