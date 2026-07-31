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
# --no-sync：环境已在构建期装好，启动时不再联网重新 sync（支持离线/内网部署）
EXPOSE 8100
ENV MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8100
CMD ["uv", "run", "--no-sync", "python", "mcp_server.py"]
