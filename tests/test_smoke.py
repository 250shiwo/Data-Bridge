"""冒烟测试：确认包可导入。"""
import databridge


def test_import():
    assert databridge is not None
