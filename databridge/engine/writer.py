"""行级写入：追加(去自增主键)、N对N按序替换、upsert 语句生成。

全部写操作单事务：任一行失败整体回滚后重抛，由上层转成结构化错误。
"""
from databridge.engine.inspector import ensure_identifier
from databridge.errors import (InvalidQueryError, SelectionCountMismatchError,
                               WriteConflictError)
import pymysql.err


def _conflict_message(exc, action: str) -> str:
    """把 pymysql 完整性错误转成中文业务提示，并保留 MySQL 的具体原因。"""
    detail = exc.args[1] if len(exc.args) > 1 else str(exc)
    return f"{action}失败：目标表存在数据完整性冲突（{detail}）"


def _qualify(db: str, table: str) -> str:
    ensure_identifier(db)
    ensure_identifier(table)
    return f"`{db}`.`{table}`"


def fetch_rows_by_pk(conn, db, table, pk_cols, pk_values):
    """按主键值列表读取行，保持入参顺序返回；有缺失主键立即报错。"""
    if not pk_values:
        return []
    target = _qualify(db, table)
    cond = " OR ".join(
        ["(" + " AND ".join([f"`{c}` = %s" for c in pk_cols]) + ")"] * len(pk_values))
    params = [v for pk in pk_values for v in pk]
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {target} WHERE {cond}", params)
        rows = cur.fetchall()
    # 按主键元组建索引，再按入参顺序输出
    index = {tuple(r[c] for c in pk_cols): r for r in rows}
    ordered = []
    for pk in pk_values:
        key = tuple(pk)
        if key not in index:
            raise InvalidQueryError(f"主键 {key} 在表 {db}.{table} 中不存在")
        ordered.append(index[key])
    return ordered


def build_append_insert(db, table, columns):
    """生成追加 INSERT：剔除自增列；非自增主键保留原样插入。"""
    names = [c["name"] for c in columns if not c["is_autoinc"]]
    cols_sql = ", ".join(f"`{n}`" for n in names)
    ph = ", ".join(["%s"] * len(names))
    return f"INSERT INTO {_qualify(db, table)} ({cols_sql}) VALUES ({ph})", names


def append_rows(conn, db, table, columns, rows) -> int:
    """单事务批量追加；失败回滚并重抛。返回插入行数。"""
    sql, names = build_append_insert(db, table, columns)
    batch = [[row[n] for n in names] for row in rows]
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, batch)
        conn.commit()
    except pymysql.err.IntegrityError as e:
        conn.rollback()
        raise WriteConflictError(_conflict_message(e, "新增")) from e
    except Exception:
        conn.rollback()
        raise
    return len(rows)


def replace_rows(conn, db, table, columns, pk_cols, src_rows, dst_pk_values) -> int:
    """N对N按序替换：目标行保留自身主键，其余列用对应源行覆盖。"""
    if len(src_rows) != len(dst_pk_values):
        raise SelectionCountMismatchError(
            f"源勾选 {len(src_rows)} 行 / 目标勾选 {len(dst_pk_values)} 行，数量必须相等")
    set_cols = [c["name"] for c in columns if c["name"] not in pk_cols]
    set_sql = ", ".join(f"`{n}` = %s" for n in set_cols)
    where_sql = " AND ".join(f"`{c}` = %s" for c in pk_cols)
    sql = f"UPDATE {_qualify(db, table)} SET {set_sql} WHERE {where_sql}"
    try:
        with conn.cursor() as cur:
            for src_row, dst_pk in zip(src_rows, dst_pk_values):
                cur.execute(sql, [src_row[n] for n in set_cols] + list(dst_pk))
        conn.commit()
    except pymysql.err.IntegrityError as e:
        conn.rollback()
        raise WriteConflictError(_conflict_message(e, "替换")) from e
    except Exception:
        conn.rollback()
        raise
    return len(src_rows)


def build_upsert(db, table, columns) -> str:
    """整表同步用：INSERT ... ON DUPLICATE KEY UPDATE（非主键列全覆盖）。"""
    names = [c["name"] for c in columns]
    non_pk = [c["name"] for c in columns if not c["is_pk"]]
    cols_sql = ", ".join(f"`{n}`" for n in names)
    ph = ", ".join(["%s"] * len(names))
    update_sql = ", ".join(f"`{n}` = VALUES(`{n}`)" for n in non_pk)
    return (f"INSERT INTO {_qualify(db, table)} ({cols_sql}) VALUES ({ph}) "
            f"ON DUPLICATE KEY UPDATE {update_sql}")
