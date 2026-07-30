"""Web 入口：FastAPI 路由薄壳，业务全部委托 SyncService。

启动：uv run uvicorn databridge.web.app:app --port 8000
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from databridge.engine.connection import check_connection
from databridge.errors import DataBridgeError
from databridge.service import SyncService
from databridge.storage.connections import ConnectionInfo, ConnectionStore

_STATIC_DIR = Path(__file__).parent / "static"


# ---------- 请求体模型 ----------

class ConnBody(BaseModel):
    alias: str
    host: str
    port: int = 3306
    user: str
    password: str = ""          # 更新时留空表示保留旧密码
    default_db: str | None = None
    protected: bool = False


class TableRef(BaseModel):
    alias: str
    db: str
    table: str


class BrowseBody(BaseModel):
    alias: str
    db: str
    table: str
    page: int = 1
    page_size: int = 50
    filters: list[dict] | None = None
    sort_column: str | None = None
    sort_dir: str = "asc"


class InsertBody(BaseModel):
    src: TableRef
    dst: TableRef
    pk_values: list[list]
    confirm: bool = False


class ReplaceBody(BaseModel):
    src: TableRef
    dst: TableRef
    src_pk_values: list[list]
    dst_pk_values: list[list]
    confirm: bool = False


class SyncBody(BaseModel):
    src: TableRef
    dst: TableRef
    where: str | None = None
    confirm: bool = False


def create_app(data_dir: Path | None = None) -> FastAPI:
    """创建应用；data_dir 可注入临时目录供测试。"""
    store = ConnectionStore(data_dir or Path("data"))
    svc = SyncService(store)
    app = FastAPI(title="DataBridge")

    @app.exception_handler(DataBridgeError)
    async def on_business_error(request: Request, exc: DataBridgeError):
        return JSONResponse(status_code=exc.http_status,
                            content={"code": exc.code, "message": exc.message})

    @app.exception_handler(Exception)
    async def on_unknown_error(request: Request, exc: Exception):
        # 不回显异常原文，避免凭据泄露；只给异常类名
        return JSONResponse(status_code=500, content={
            "code": "internal_error",
            "message": f"服务内部错误：{type(exc).__name__}"})

    # ---------- 连接管理 ----------

    @app.get("/api/connections")
    def list_connections():
        return store.list_safe()

    @app.post("/api/connections")
    def save_connection(body: ConnBody):
        store.save(ConnectionInfo(**body.model_dump()))
        return {"ok": True}

    @app.delete("/api/connections/{alias}")
    def delete_connection(alias: str):
        store.delete(alias)
        return {"ok": True}

    @app.post("/api/connections/test")
    def test_connection(body: ConnBody):
        info = ConnectionInfo(**body.model_dump())
        if body.password == "":
            # 编辑态不改密码时，用已存密码测试
            info = store.get(body.alias)
        ok = check_connection(info)
        return {"ok": ok}

    # ---------- 元数据与浏览 ----------

    @app.get("/api/databases")
    def list_databases(alias: str):
        return svc.list_databases(alias)

    @app.get("/api/tables")
    def list_tables(alias: str, db: str):
        return svc.list_tables(alias, db)

    @app.post("/api/browse")
    def browse(body: BrowseBody):
        return svc.browse_table(body.alias, body.db, body.table, body.page,
                                body.page_size, body.filters,
                                body.sort_column, body.sort_dir)

    # ---------- 勾选行同步 ----------

    @app.post("/api/rows/insert")
    def rows_insert(body: InsertBody):
        return svc.insert_rows(body.src.model_dump(), body.dst.model_dump(),
                               body.pk_values, body.confirm)

    @app.post("/api/rows/replace")
    def rows_replace(body: ReplaceBody):
        return svc.replace_rows(body.src.model_dump(), body.dst.model_dump(),
                                body.src_pk_values, body.dst_pk_values,
                                body.confirm)

    # ---------- 整表同步 ----------

    @app.post("/api/sync/preview")
    def sync_preview(body: SyncBody):
        return svc.preview_sync(body.src.model_dump(), body.dst.model_dump(),
                                body.where)

    @app.post("/api/sync/execute")
    def sync_execute(body: SyncBody):
        return svc.execute_sync(body.src.model_dump(), body.dst.model_dump(),
                                body.where, body.confirm)

    # 静态页面（前端在 Task 10 交付；目录不存在时跳过，保证测试可跑）
    if _STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
    return app


app = create_app()
