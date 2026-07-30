"""整表增量比对：主键逐行、keyset 分批，preview 只读、execute 分批 upsert。"""
from databridge.engine.inspector import ensure_identifier
from databridge.engine.writer import build_upsert

_SAMPLE_LIMIT = 10  # preview 返回的主键示例上限


def _qualify(db, table):
    ensure_identifier(db)
    ensure_identifier(table)
    return f"`{db}`.`{table}`"


def _pk_tuple(row, pk_cols):
    return tuple(row[c] for c in pk_cols)


def iter_source_batches(conn, db, table, pk_cols, where=None, batch_size=1000):
    """按主键排序 keyset 分页逐批读源表。where 为可选的原样 SQL 条件。

    注意：where 由使用者（GUI 输入）提供，仅用于源表读取，不参与写入拼接。
    """
    target = _qualify(db, table)
    order = ", ".join(f"`{c}`" for c in pk_cols)
    last_pk = None
    while True:
        conds, params = [], []
        if where:
            conds.append(f"({where})")
        if last_pk is not None:
            # 复合主键用行值比较实现 keyset 分页
            pk_expr = "(" + ", ".join(f"`{c}`" for c in pk_cols) + ")"
            conds.append(f"{pk_expr} > (" + ", ".join(["%s"] * len(pk_cols)) + ")")
            params.extend(last_pk)
        where_sql = (" WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"SELECT * FROM {target}{where_sql} ORDER BY {order} LIMIT %s"
        with conn.cursor() as cur:
            cur.execute(sql, params + [batch_size])
            batch = cur.fetchall()
        if not batch:
            return
        yield batch
        last_pk = _pk_tuple(batch[-1], pk_cols)


def _fetch_dst_rows(dst_conn, dst_db, dst_table, pk_cols, src_batch):
    """按源批次的主键集合查目标表现有行。"""
    target = _qualify(dst_db, dst_table)
    cond = " OR ".join(
        ["(" + " AND ".join(f"`{c}` = %s" for c in pk_cols) + ")"] * len(src_batch))
    params = [v for row in src_batch for v in _pk_tuple(row, pk_cols)]
    with dst_conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {target} WHERE {cond}", params)
        return cur.fetchall()


def classify_batch(src_batch, dst_rows, pk_cols):
    """比对一批：返回 (目标缺失的新增行, 内容不同的变更行)。"""
    dst_index = {_pk_tuple(r, pk_cols): r for r in dst_rows}
    inserts, updates = [], []
    for row in src_batch:
        dst = dst_index.get(_pk_tuple(row, pk_cols))
        if dst is None:
            inserts.append(row)
        elif dict(dst) != dict(row):
            updates.append(row)
    return inserts, updates


def preview_diff(src_conn, dst_conn, src_db, src_table, dst_db, dst_table,
                 columns, pk_cols, where=None, batch_size=1000):
    """dry-run：统计将新增/覆盖的行数与主键示例，不写任何数据。"""
    to_insert = to_update = 0
    sample_pks = []
    for batch in iter_source_batches(src_conn, src_db, src_table,
                                     pk_cols, where, batch_size):
        dst_rows = _fetch_dst_rows(dst_conn, dst_db, dst_table, pk_cols, batch)
        inserts, updates = classify_batch(batch, dst_rows, pk_cols)
        to_insert += len(inserts)
        to_update += len(updates)
        for row in inserts + updates:
            if len(sample_pks) < _SAMPLE_LIMIT:
                sample_pks.append(list(_pk_tuple(row, pk_cols)))
    return {"to_insert": to_insert, "to_update": to_update,
            "sample_pks": sample_pks}


def execute_diff_sync(src_conn, dst_conn, src_db, src_table, dst_db, dst_table,
                      columns, pk_cols, where=None, batch_size=1000):
    """执行同步：逐批 upsert 差异行（新增+变更），失败回滚重抛。"""
    names = [c["name"] for c in columns]
    upsert_sql = build_upsert(dst_db, dst_table, columns)
    inserted = updated = 0
    try:
        for batch in iter_source_batches(src_conn, src_db, src_table,
                                         pk_cols, where, batch_size):
            dst_rows = _fetch_dst_rows(dst_conn, dst_db, dst_table, pk_cols, batch)
            inserts, updates = classify_batch(batch, dst_rows, pk_cols)
            changed = inserts + updates
            if changed:
                values = [[row[n] for n in names] for row in changed]
                with dst_conn.cursor() as cur:
                    cur.executemany(upsert_sql, values)
            inserted += len(inserts)
            updated += len(updates)
        dst_conn.commit()
    except Exception:
        dst_conn.rollback()
        raise
    return {"inserted": inserted, "updated": updated}
