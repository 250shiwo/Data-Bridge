"""行级写入测试：追加去自增、替换按序配对、事务回滚、upsert 语句。"""
import pytest

from databridge.engine import writer
from databridge.errors import (InvalidQueryError, SelectionCountMismatchError,
                               WriteConflictError)
from tests.conftest import FakeConnection


def col(name, is_pk=False, is_autoinc=False):
    return {"name": name, "type": "int", "is_pk": is_pk, "is_autoinc": is_autoinc}

COLS_AUTOINC = [col("id", True, True), col("a"), col("b")]
COLS_PLAIN_PK = [col("code", True, False), col("a"), col("b")]


def test_build_append_insert_strips_autoinc():
    sql, names = writer.build_append_insert("d", "t", COLS_AUTOINC)
    assert sql == "INSERT INTO `d`.`t` (`a`, `b`) VALUES (%s, %s)"
    assert names == ["a", "b"]


def test_build_append_insert_keeps_non_autoinc_pk():
    sql, names = writer.build_append_insert("d", "t", COLS_PLAIN_PK)
    assert names == ["code", "a", "b"]


def test_append_rows_commits():
    conn = FakeConnection()
    n = writer.append_rows(conn, "d", "t", COLS_AUTOINC,
                           [{"id": 1, "a": 10, "b": 20}, {"id": 2, "a": 30, "b": 40}])
    assert n == 2
    assert conn.committed is True
    sql, batch = conn.cursor_obj.executed[0]
    assert batch == [[10, 20], [30, 40]]   # 自增 id 被剔除


def test_append_rows_rolls_back_on_error():
    conn = FakeConnection(error=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        writer.append_rows(conn, "d", "t", COLS_AUTOINC, [{"id": 1, "a": 1, "b": 2}])
    assert conn.rolled_back is True
    assert conn.committed is False


def test_append_rows_maps_integrity_error_to_conflict():
    """唯一键冲突等完整性错误应转成业务冲突错误（带 MySQL 原因）。"""
    import pymysql.err
    conn = FakeConnection(error=pymysql.err.IntegrityError(
        1062, "Duplicate entry '开发' for key 'auth_group.name'"))
    with pytest.raises(WriteConflictError) as ei:
        writer.append_rows(conn, "d", "t", COLS_AUTOINC, [{"id": 1, "a": 1, "b": 2}])
    assert conn.rolled_back is True
    assert conn.committed is False
    assert "Duplicate entry" in ei.value.message   # 保留 MySQL 具体原因
    assert "新增" in ei.value.message              # 中文动作词


def test_replace_rows_count_mismatch():
    conn = FakeConnection()
    with pytest.raises(SelectionCountMismatchError):
        writer.replace_rows(conn, "d", "t", COLS_AUTOINC, ["id"],
                            src_rows=[{"id": 1, "a": 1, "b": 2}],
                            dst_pk_values=[[7], [8]])


def test_replace_rows_pairs_in_order():
    conn = FakeConnection()
    n = writer.replace_rows(
        conn, "d", "t", COLS_AUTOINC, ["id"],
        src_rows=[{"id": 1, "a": 10, "b": 20}, {"id": 2, "a": 30, "b": 40}],
        dst_pk_values=[[7], [8]])
    assert n == 2
    assert conn.committed is True
    sql1, params1 = conn.cursor_obj.executed[0]
    assert sql1 == "UPDATE `d`.`t` SET `a` = %s, `b` = %s WHERE `id` = %s"
    assert params1 == [10, 20, 7]          # 源第1行 -> 目标主键7，保留目标主键
    _, params2 = conn.cursor_obj.executed[1]
    assert params2 == [30, 40, 8]


def test_fetch_rows_by_pk_preserves_order_and_checks_missing():
    conn = FakeConnection(results=[[{"id": 2, "a": 1}, {"id": 1, "a": 2}]])
    rows = writer.fetch_rows_by_pk(conn, "d", "t", ["id"], [[1], [2]])
    assert [r["id"] for r in rows] == [1, 2]   # 按入参顺序返回

    conn2 = FakeConnection(results=[[{"id": 1, "a": 2}]])
    with pytest.raises(InvalidQueryError):
        writer.fetch_rows_by_pk(conn2, "d", "t", ["id"], [[1], [99]])


def test_build_upsert():
    sql = writer.build_upsert("d", "t", COLS_AUTOINC)
    assert sql == ("INSERT INTO `d`.`t` (`id`, `a`, `b`) VALUES (%s, %s, %s) "
                   "ON DUPLICATE KEY UPDATE `a` = VALUES(`a`), `b` = VALUES(`b`)")
