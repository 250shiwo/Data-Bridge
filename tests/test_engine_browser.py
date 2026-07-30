"""数据浏览查询测试：SQL 生成、筛选/排序白名单、分页。"""
import pytest

from databridge.engine.browser import browse, build_browse_query
from databridge.errors import InvalidQueryError
from tests.conftest import FakeConnection

ALLOWED = {"id", "name"}


def test_basic_pagination_sql():
    sql, params, count_sql, count_params = build_browse_query(
        "db1", "t1", ALLOWED, page=3, page_size=50,
        filters=None, sort_column=None, sort_dir="asc")
    assert sql == "SELECT * FROM `db1`.`t1` LIMIT %s OFFSET %s"
    assert params == [50, 100]
    assert count_sql == "SELECT COUNT(*) AS total FROM `db1`.`t1`"
    assert count_params == []


def test_filters_and_sort():
    sql, params, count_sql, count_params = build_browse_query(
        "db1", "t1", ALLOWED, page=1, page_size=10,
        filters=[{"column": "name", "op": "contains", "value": "abc"},
                 {"column": "id", "op": "gte", "value": 5}],
        sort_column="id", sort_dir="desc")
    assert "WHERE `name` LIKE %s AND `id` >= %s" in sql
    assert "ORDER BY `id` DESC" in sql
    assert params == ["%abc%", 5, 10, 0]
    assert count_params == ["%abc%", 5]


def test_illegal_filter_column_rejected():
    with pytest.raises(InvalidQueryError):
        build_browse_query("db1", "t1", ALLOWED, 1, 10,
                           filters=[{"column": "pwd; --", "op": "eq", "value": 1}],
                           sort_column=None, sort_dir="asc")


def test_illegal_sort_rejected():
    with pytest.raises(InvalidQueryError):
        build_browse_query("db1", "t1", ALLOWED, 1, 10, None, "id", "evil")


def test_browse_returns_rows_and_total():
    conn = FakeConnection(results=[
        [{"total": 2}],                          # 计数查询结果
        [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],  # 数据查询结果
    ])
    cols = [{"name": "id", "type": "int", "is_pk": True, "is_autoinc": True},
            {"name": "name", "type": "varchar", "is_pk": False, "is_autoinc": False}]
    out = browse(conn, "db1", "t1", cols)
    assert out["total"] == 2
    assert len(out["rows"]) == 2
