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

    return mcp
