"""服务层测试：受保护连接护栏、insert/replace 编排（fake 连接注入）。"""
import pytest

from databridge.errors import ProtectedConnectionError
from databridge.service import SyncService
from databridge.storage.connections import ConnectionInfo, ConnectionStore
from tests.conftest import FakeConnection


@pytest.fixture
def store(tmp_path):
    s = ConnectionStore(tmp_path)
    s.save(ConnectionInfo(alias="dev", host="h", port=3306, user="u",
                          password="p", default_db=None, protected=False))
    s.save(ConnectionInfo(alias="prod", host="h", port=3306, user="u",
                          password="p", default_db=None, protected=True))
    return s

SRC = {"alias": "dev", "db": "s", "table": "t"}
DST_PROD = {"alias": "prod", "db": "d", "table": "t"}

COL_META = [
    {"name": "id", "type": "int", "is_pk": 1, "is_autoinc": 1},
    {"name": "a", "type": "int", "is_pk": 0, "is_autoinc": 0},
]


def test_write_to_protected_without_confirm_rejected(store):
    svc = SyncService(store, connect=lambda info, db=None: FakeConnection())
    with pytest.raises(ProtectedConnectionError) as ei:
        svc.insert_rows(SRC, DST_PROD, pk_values=[[1]], confirm=False)
    assert "受保护" in ei.value.message


def test_replace_and_execute_also_guarded(store):
    svc = SyncService(store, connect=lambda info, db=None: FakeConnection())
    with pytest.raises(ProtectedConnectionError):
        svc.replace_rows(SRC, DST_PROD, [[1]], [[2]], confirm=False)
    with pytest.raises(ProtectedConnectionError):
        svc.execute_sync(SRC, DST_PROD, confirm=False)


def test_insert_rows_happy_path(store):
    # 依连接打开顺序注入结果集：
    # 源连接：get_columns、fetch_rows_by_pk；目标连接：get_columns
    conns = [
        FakeConnection(results=[COL_META, [{"id": 1, "a": 10}]]),   # 源
        FakeConnection(results=[COL_META]),                          # 目标
    ]
    svc = SyncService(store, connect=lambda info, db=None: conns.pop(0))
    out = svc.insert_rows(SRC, {"alias": "dev", "db": "d", "table": "t"},
                          pk_values=[[1]], confirm=False)
    assert out == {"inserted": 1}
