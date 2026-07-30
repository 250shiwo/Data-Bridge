"""元数据检查器测试：列/主键识别、一致性校验、标识符校验。"""
import pytest

from databridge.engine import inspector
from databridge.errors import (ColumnMismatchError, InvalidQueryError,
                               NoPrimaryKeyError, PrimaryKeyMismatchError,
                               TableNotFoundError)
from tests.conftest import FakeConnection


def col(name, is_pk=False, is_autoinc=False, type_="int"):
    return {"name": name, "type": type_, "is_pk": is_pk, "is_autoinc": is_autoinc}


def test_get_columns_parses_metadata():
    conn = FakeConnection(results=[[
        {"name": "id", "type": "int", "is_pk": 1, "is_autoinc": 1},
        {"name": "title", "type": "varchar", "is_pk": 0, "is_autoinc": 0},
    ]])
    cols = inspector.get_columns(conn, "db1", "t1")
    assert cols == [col("id", True, True), col("title", type_="varchar")]


def test_get_columns_missing_table_raises():
    conn = FakeConnection(results=[[]])
    with pytest.raises(TableNotFoundError):
        inspector.get_columns(conn, "db1", "nope")


def test_get_primary_key():
    cols = [col("id", True, True), col("title", type_="varchar")]
    assert inspector.get_primary_key(cols, "db1", "t1") == ["id"]
    with pytest.raises(NoPrimaryKeyError):
        inspector.get_primary_key([col("title")], "db1", "t1")


def test_check_columns_match_ignores_autoinc():
    src = [col("id", True, True), col("a"), col("b")]
    dst = [col("nid", True, True), col("a"), col("b")]
    inspector.check_columns_match(src, dst)  # 自增主键名不同也算一致


def test_check_columns_match_reports_diff():
    src = [col("a"), col("only_src")]
    dst = [col("a"), col("only_dst")]
    with pytest.raises(ColumnMismatchError) as ei:
        inspector.check_columns_match(src, dst)
    assert "only_src" in ei.value.message
    assert "only_dst" in ei.value.message


def test_check_pk_match():
    src = [col("id", True), col("a")]
    dst = [col("code", True), col("a")]
    with pytest.raises(PrimaryKeyMismatchError):
        inspector.check_pk_match(src, dst)


def test_ensure_identifier():
    assert inspector.ensure_identifier("my_table$1") == "my_table$1"
    with pytest.raises(InvalidQueryError):
        inspector.ensure_identifier("t; DROP TABLE x")
    with pytest.raises(InvalidQueryError):
        inspector.ensure_identifier("t1\n")   # 末尾换行不得逃逸 $ 锚定
