"""连接配置存储测试：加密往返、无明文、空密码保留、删除。"""
import json
import pytest

from databridge.errors import ConnectionNotFoundError
from databridge.storage.connections import ConnectionInfo, ConnectionStore


def make_info(**kw) -> ConnectionInfo:
    base = dict(alias="dev", host="127.0.0.1", port=3306, user="root",
                password="s3cret!", default_db=None, protected=False)
    base.update(kw)
    return ConnectionInfo(**base)


def test_save_and_get_roundtrip(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info())
    got = store.get("dev")
    assert got.password == "s3cret!"
    assert got.host == "127.0.0.1"
    assert got.protected is False


def test_file_has_no_plaintext_password(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info())
    raw = (tmp_path / "connections.json").read_text(encoding="utf-8")
    assert "s3cret!" not in raw


def test_list_safe_excludes_password(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info(protected=True))
    items = store.list_safe()
    assert items == [{"alias": "dev", "host": "127.0.0.1", "port": 3306,
                      "user": "root", "default_db": None, "protected": True}]


def test_update_with_blank_password_keeps_old(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info())
    store.save(make_info(password="", host="10.0.0.2"))
    got = store.get("dev")
    assert got.password == "s3cret!"
    assert got.host == "10.0.0.2"


def test_get_missing_raises(tmp_path):
    store = ConnectionStore(tmp_path)
    with pytest.raises(ConnectionNotFoundError):
        store.get("nope")


def test_delete(tmp_path):
    store = ConnectionStore(tmp_path)
    store.save(make_info())
    store.delete("dev")
    with pytest.raises(ConnectionNotFoundError):
        store.get("dev")
