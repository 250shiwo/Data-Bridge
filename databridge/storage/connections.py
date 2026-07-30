"""连接配置存取：本地 JSON 持久化，密码 Fernet 加密。

密钥文件 data/.key 首次使用时自动生成；data/ 整体在 .gitignore 中。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

from databridge.errors import ConnectionNotFoundError


@dataclass
class ConnectionInfo:
    """一条 MySQL 连接配置（password 为明文，仅存在于内存）。"""
    alias: str
    host: str
    port: int
    user: str
    password: str
    default_db: str | None = None
    protected: bool = False


class ConnectionStore:
    """连接配置仓库：list_safe 永不返回密码。"""

    def __init__(self, data_dir: Path):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "connections.json"
        key_file = self._dir / ".key"
        if not key_file.exists():
            key_file.write_bytes(Fernet.generate_key())
        self._fernet = Fernet(key_file.read_bytes())

    def _load(self) -> dict:
        if not self._file.exists():
            return {}
        return json.loads(self._file.read_text(encoding="utf-8"))

    def _save_file(self, data: dict) -> None:
        self._file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_safe(self) -> list[dict]:
        """列出全部连接（不含任何密码字段）。"""
        return [
            {"alias": alias, "host": item["host"], "port": item["port"],
             "user": item["user"], "default_db": item.get("default_db"),
             "protected": item.get("protected", False)}
            for alias, item in sorted(self._load().items())
        ]

    def get(self, alias: str) -> ConnectionInfo:
        data = self._load()
        if alias not in data:
            raise ConnectionNotFoundError(f"连接 {alias} 不存在")
        item = data[alias]
        password = self._fernet.decrypt(item["password_enc"].encode()).decode()
        return ConnectionInfo(
            alias=alias, host=item["host"], port=item["port"],
            user=item["user"], password=password,
            default_db=item.get("default_db"),
            protected=item.get("protected", False))

    def save(self, info: ConnectionInfo) -> None:
        """新增或更新；更新时 password 为空字符串表示保留旧密码。"""
        data = self._load()
        if info.password == "" and info.alias in data:
            password_enc = data[info.alias]["password_enc"]
        else:
            password_enc = self._fernet.encrypt(info.password.encode()).decode()
        data[info.alias] = {
            "host": info.host, "port": info.port, "user": info.user,
            "password_enc": password_enc, "default_db": info.default_db,
            "protected": info.protected}
        self._save_file(data)

    def delete(self, alias: str) -> None:
        data = self._load()
        if alias not in data:
            raise ConnectionNotFoundError(f"连接 {alias} 不存在")
        del data[alias]
        self._save_file(data)
