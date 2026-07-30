"""Web API 冒烟测试：连接 CRUD、护栏 403、错误结构、无密码回显。"""
import pytest
from fastapi.testclient import TestClient

from databridge.web.app import create_app

CONN_BODY = {"alias": "dev", "host": "127.0.0.1", "port": 3306, "user": "root",
             "password": "pw!", "default_db": None, "protected": False}
PROD_BODY = dict(CONN_BODY, alias="prod", protected=True)


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=tmp_path)
    return TestClient(app)


def test_connection_crud_and_no_password_leak(client):
    r = client.post("/api/connections", json=CONN_BODY)
    assert r.status_code == 200
    r = client.get("/api/connections")
    assert r.status_code == 200
    assert r.json() == [{"alias": "dev", "host": "127.0.0.1", "port": 3306,
                         "user": "root", "default_db": None, "protected": False}]
    assert "pw!" not in r.text
    r = client.delete("/api/connections/dev")
    assert r.status_code == 200
    assert client.get("/api/connections").json() == []


def test_delete_missing_connection_404(client):
    r = client.delete("/api/connections/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "connection_not_found"
    assert "不存在" in body["message"]


def test_protected_write_without_confirm_403(client):
    client.post("/api/connections", json=CONN_BODY)
    client.post("/api/connections", json=PROD_BODY)
    r = client.post("/api/rows/insert", json={
        "src": {"alias": "dev", "db": "s", "table": "t"},
        "dst": {"alias": "prod", "db": "d", "table": "t"},
        "pk_values": [[1]], "confirm": False})
    assert r.status_code == 403
    assert r.json()["code"] == "protected_connection"


def test_sync_execute_also_guarded(client):
    client.post("/api/connections", json=CONN_BODY)
    client.post("/api/connections", json=PROD_BODY)
    r = client.post("/api/sync/execute", json={
        "src": {"alias": "dev", "db": "s", "table": "t"},
        "dst": {"alias": "prod", "db": "d", "table": "t"},
        "confirm": False})
    assert r.status_code == 403
