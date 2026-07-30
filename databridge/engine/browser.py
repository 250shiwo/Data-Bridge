"""数据浏览：分页查询 + 列筛选 + 排序，全部经白名单校验。"""
from databridge.engine.inspector import ensure_identifier
from databridge.errors import InvalidQueryError

# 筛选操作符 -> SQL 片段（占位符统一 %s）
_OPS = {"eq": "= %s", "contains": "LIKE %s", "gte": ">= %s", "lte": "<= %s"}


def _build_where(filters, allowed_columns):
    clauses, params = [], []
    for f in filters or []:
        col, op, value = f.get("column"), f.get("op"), f.get("value")
        if col not in allowed_columns:
            raise InvalidQueryError(f"非法筛选列：{col!r}")
        if op not in _OPS:
            raise InvalidQueryError(f"非法筛选操作：{op!r}")
        clauses.append(f"`{col}` {_OPS[op]}")
        params.append(f"%{value}%" if op == "contains" else value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def build_browse_query(db, table, allowed_columns, page, page_size,
                       filters, sort_column, sort_dir):
    """生成 (数据SQL, 数据参数, 计数SQL, 计数参数)，列名经白名单校验。"""
    ensure_identifier(db)
    ensure_identifier(table)
    where, params = _build_where(filters, allowed_columns)
    order = ""
    if sort_column:
        if sort_column not in allowed_columns:
            raise InvalidQueryError(f"非法排序列：{sort_column!r}")
        if sort_dir not in ("asc", "desc"):
            raise InvalidQueryError(f"非法排序方向：{sort_dir!r}")
        order = f" ORDER BY `{sort_column}` {sort_dir.upper()}"
    offset = (page - 1) * page_size
    sql = f"SELECT * FROM `{db}`.`{table}`{where}{order} LIMIT %s OFFSET %s"
    count_sql = f"SELECT COUNT(*) AS total FROM `{db}`.`{table}`{where}"
    return sql, params + [page_size, offset], count_sql, list(params)


def browse(conn, db, table, columns, page=1, page_size=50,
           filters=None, sort_column=None, sort_dir="asc"):
    """执行浏览查询，返回 {"rows", "total"}。columns 来自 inspector.get_columns。"""
    allowed = {c["name"] for c in columns}
    sql, params, count_sql, count_params = build_browse_query(
        db, table, allowed, page, page_size, filters, sort_column, sort_dir)
    with conn.cursor() as cur:
        cur.execute(count_sql, count_params)
        total = cur.fetchone()["total"]
        cur.execute(sql, params)
        rows = cur.fetchall()
    return {"rows": rows, "total": total}
