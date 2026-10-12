from datetime import datetime, timezone


def build_error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
