"""元数据检查器：列结构、主键识别、一致性校验、标识符防注入。"""
import re

from databridge.errors import (ColumnMismatchError, InvalidQueryError,
                               NoPrimaryKeyError, PrimaryKeyMismatchError,
                               TableNotFoundError)

_IDENT_RE = re.compile(r"^[0-9A-Za-z_$]+$")


def ensure_identifier(name: str) -> str:
    """校验库/表/列标识符只含安全字符，否则拒绝（防 SQL 注入）。"""
    if not name or not _IDENT_RE.match(name):
        raise InvalidQueryError(f"非法标识符：{name!r}")
    return name


def list_databases(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW DATABASES")
        return [list(row.values())[0] for row in cur.fetchall()]


def list_tables(conn, db: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME", (db,))
        return [row["name"] for row in cur.fetchall()]


def get_columns(conn, db: str, table: str) -> list[dict]:
    """查询列元数据；表不存在（无任何列）时报 TableNotFoundError。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COLUMN_NAME AS name, DATA_TYPE AS type, "
            "COLUMN_KEY = 'PRI' AS is_pk, "
            "EXTRA LIKE '%%auto_increment%%' AS is_autoinc "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION", (db, table))
        rows = cur.fetchall()
    if not rows:
        raise TableNotFoundError(f"表 {db}.{table} 不存在")
    return [{"name": r["name"], "type": r["type"],
             "is_pk": bool(r["is_pk"]), "is_autoinc": bool(r["is_autoinc"])}
            for r in rows]


def get_primary_key(columns: list[dict], db: str, table: str) -> list[str]:
    pk = [c["name"] for c in columns if c["is_pk"]]
    if not pk:
        raise NoPrimaryKeyError(f"表 {db}.{table} 没有主键，无法同步")
    return pk


def check_columns_match(src_cols: list[dict], dst_cols: list[dict]) -> None:
    """校验两表列名集合完全一致（自增列除外），不一致时列出差异列。"""
    src = {c["name"] for c in src_cols if not c["is_autoinc"]}
    dst = {c["name"] for c in dst_cols if not c["is_autoinc"]}
    if src != dst:
        only_src = sorted(src - dst)
        only_dst = sorted(dst - src)
        raise ColumnMismatchError(
            f"两表列结构不一致：仅源表有 {only_src}，仅目标表有 {only_dst}")


def check_pk_match(src_cols: list[dict], dst_cols: list[dict]) -> None:
    """整表同步前置校验：主键列名列表必须一致。"""
    src_pk = [c["name"] for c in src_cols if c["is_pk"]]
    dst_pk = [c["name"] for c in dst_cols if c["is_pk"]]
    if src_pk != dst_pk:
        raise PrimaryKeyMismatchError(
            f"两表主键结构不一致：源表 {src_pk}，目标表 {dst_pk}")
