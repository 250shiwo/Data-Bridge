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
