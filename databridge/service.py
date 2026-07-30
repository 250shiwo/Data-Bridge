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
