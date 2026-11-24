"""控制台业务错误：带 HTTP 状态码，由 HTTP 层统一转换。"""

from __future__ import annotations


class ControlError(RuntimeError):
    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
