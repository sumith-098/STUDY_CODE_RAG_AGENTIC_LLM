"""
errors.py  --  Friendly errors.

Idea: user ko kabhi "Unknown error / 500 / traceback" na dikhe. Har problem ka
ek code + saaf message + (agar ho) retry_after seconds hota hai.
Frontend isi format ko padhta hai:
    {"error": {"code": "daily_quota", "message": "...", "retry_after": 3600}}
"""

class AppError(Exception):
    """Base class. status_code = HTTP status, code = machine-readable naam."""
    status_code = 500
    code = "server_error"

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after

    def to_dict(self) -> dict:
        """Returns: {'error': {'code': str, 'message': str, 'retry_after': int|None}}"""
        return {"error": {"code": self.code, "message": self.message,
                          "retry_after": self.retry_after}}

class BadInput(AppError):
    """User ne galat file/input diya."""
    status_code = 400
    code = "bad_input"

class QuotaExceeded(AppError):
    """Free tier limit khatam (minute ya din ki)."""
    status_code = 429
    code = "quota"

class UpstreamBusy(AppError):
    """Google ka server busy / down hai."""
    status_code = 503
    code = "upstream_busy"

class ConfigProblem(AppError):
    """API key ya model ID galat hai -- user ke bas me nahi, owner ko theek karna hai."""
    status_code = 503
    code = "config"
