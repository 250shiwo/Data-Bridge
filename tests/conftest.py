"""共享测试桩：模拟 pymysql 连接/游标，供引擎层单测复用。"""
from __future__ import annotations


class FakeCursor:
    """极简游标桩：按顺序弹出预置结果集，记录执行过的 SQL 与参数。"""

    def __init__(self, results: list | None = None, error: Exception | None = None):
        self.results = list(results or [])   # 每次 execute 弹出一个结果集(list[dict])
        self.error = error                   # 置为异常时，execute/executemany 抛出
        self.executed: list[tuple] = []      # [(sql, params), ...]
        self._current: list = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.error:
            raise self.error
        self._current = self.results.pop(0) if self.results else []

    def executemany(self, sql, seq_params):
        self.executed.append((sql, list(seq_params)))
        if self.error:
            raise self.error

    def fetchall(self):
        return self._current

    def fetchone(self):
        return self._current[0] if self._current else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    """极简连接桩：单游标，记录 commit/rollback 调用。"""

    def __init__(self, results: list | None = None, error: Exception | None = None):
        self.cursor_obj = FakeCursor(results, error)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True
