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
