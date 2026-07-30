"""连接封装测试：确认 pymysql.connect 收到正确参数。"""
from unittest.mock import patch, MagicMock

from databridge.engine.connection import open_connection, check_connection
from databridge.storage.connections import ConnectionInfo

INFO = ConnectionInfo(alias="dev", host="db.local", port=3307,
                      user="u", password="p", default_db=None, protected=False)


@patch("databridge.engine.connection.pymysql")
def test_open_connection_kwargs(mock_pymysql):
    open_connection(INFO, database="mydb")
    kwargs = mock_pymysql.connect.call_args.kwargs
    assert kwargs["host"] == "db.local"
    assert kwargs["port"] == 3307
    assert kwargs["database"] == "mydb"
    assert kwargs["autocommit"] is False
    assert kwargs["charset"] == "utf8mb4"


@patch("databridge.engine.connection.pymysql")
def test_check_connection_pings_and_closes(mock_pymysql):
    conn = MagicMock()
    mock_pymysql.connect.return_value = conn
    assert check_connection(INFO) is True
    conn.ping.assert_called_once()
    conn.close.assert_called_once()
