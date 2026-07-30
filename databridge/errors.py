"""业务可预期错误体系：携带错误码、HTTP 状态与中文提示。"""


class DataBridgeError(Exception):
    """所有业务错误的基类。"""
    code = "internal_error"
    http_status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConnectionNotFoundError(DataBridgeError):
    code = "connection_not_found"
    http_status = 404


class ProtectedConnectionError(DataBridgeError):
    code = "protected_connection"
    http_status = 403


class TableNotFoundError(DataBridgeError):
    code = "table_not_found"
    http_status = 404


class NoPrimaryKeyError(DataBridgeError):
    code = "no_primary_key"


class ColumnMismatchError(DataBridgeError):
    code = "column_mismatch"


class PrimaryKeyMismatchError(DataBridgeError):
    code = "primary_key_mismatch"


class SelectionCountMismatchError(DataBridgeError):
    code = "selection_count_mismatch"


class WriteConflictError(DataBridgeError):
    # 写入违反目标表约束（如唯一键/外键/非空），用 409 表达“资源冲突”
    code = "write_conflict"
    http_status = 409


class InvalidQueryError(DataBridgeError):
    code = "invalid_query"
