"""토스 API 에러 envelope → 예외. 가공 없이 code/message/data/requestId 보존."""
from __future__ import annotations


class TossApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 data: dict | None = None, request_id: str | None = None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.data = data
        self.request_id = request_id


class GuardError(Exception):
    """자체 가드 거부. code 는 'guard/…'."""

    def __init__(self, code: str, message: str, data: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data
