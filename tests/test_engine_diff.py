"""整表增量比对测试：新增/变更判定、preview 统计、execute upsert。"""
from databridge.engine import diff
from tests.conftest import FakeConnection


def col(name, is_pk=False, is_autoinc=False):
    return {"name": name, "type": "int", "is_pk": is_pk, "is_autoinc": is_autoinc}

COLS = [col("id", True), col("v")]


def test_classify_batch():
    src = [{"id": 1, "v": 10}, {"id": 2, "v": 20}, {"id": 3, "v": 30}]
    dst = [{"id": 1, "v": 10},   # 相同 -> 跳过
           {"id": 2, "v": 99}]   # 不同 -> 变更；id=3 目标缺失 -> 新增
    inserts, updates = diff.classify_batch(src, dst, ["id"])
    assert [r["id"] for r in inserts] == [3]
    assert [r["id"] for r in updates] == [2]


def test_preview_diff_counts():
    # 源第一批返回 3 行，第二批返回空(结束)；目标按主键查回 2 行
    src_conn = FakeConnection(results=[
        [{"id": 1, "v": 10}, {"id": 2, "v": 20}, {"id": 3, "v": 30}],
        [],
    ])
    dst_conn = FakeConnection(results=[
        [{"id": 1, "v": 10}, {"id": 2, "v": 99}],
    ])
    out = diff.preview_diff(src_conn, dst_conn, "s", "t1", "d", "t2",
                            COLS, ["id"], batch_size=10)
    assert out == {"to_insert": 1, "to_update": 1, "sample_pks": [[3], [2]]}
    assert dst_conn.committed is False   # 预览绝不写数据


def test_execute_diff_sync_upserts_only_changed():
    src_conn = FakeConnection(results=[
        [{"id": 1, "v": 10}, {"id": 2, "v": 20}, {"id": 3, "v": 30}],
        [],
    ])
    dst_conn = FakeConnection(results=[
        [{"id": 1, "v": 10}, {"id": 2, "v": 99}],
    ])
    out = diff.execute_diff_sync(src_conn, dst_conn, "s", "t1", "d", "t2",
                                 COLS, ["id"], batch_size=10)
    assert out == {"inserted": 1, "updated": 1}
    assert dst_conn.committed is True
    # 找到 executemany 的 upsert 调用：只带 id=3(新增) 和 id=2(变更) 两行
    upsert_calls = [(s, p) for s, p in dst_conn.cursor_obj.executed
                    if s.startswith("INSERT INTO")]
    assert len(upsert_calls) == 1
    assert upsert_calls[0][1] == [[3, 30], [2, 20]]
