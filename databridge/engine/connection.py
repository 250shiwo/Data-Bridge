"""MySQL 连接封装：统一 DictCursor、手动提交、utf8mb4。"""
import pymysql
import pymysql.cursors

from databridge.storage.connections import ConnectionInfo


def open_connection(info: ConnectionInfo, database: str | None = None):
    """按连接配置打开 MySQL 连接；database 为 None 时不选库。"""
    return pymysql.connect(
        host=info.host, port=info.port, user=info.user,
        password=info.password, database=database,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False, charset="utf8mb4")


def check_connection(info: ConnectionInfo) -> bool:
    """连通性测试：ping 一次即断开。失败时由调用方捕获异常。"""
    conn = open_connection(info)
    try:
        conn.ping()
        return True
    finally:
        conn.close()
