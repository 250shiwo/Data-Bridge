"""MCP stdio 入口：agent 以子进程拉起（uv --directory <项目> run python mcp_server.py）。"""
from databridge.mcp.server import create_mcp

if __name__ == "__main__":
    create_mcp().run()  # FastMCP 默认 stdio 传输
