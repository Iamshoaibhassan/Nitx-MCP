def job_key(job_id: str) -> str:
    return f"poster:job:{job_id}"


def idempotency_key(key: str) -> str:
    return f"poster:idempotency:{key}"


def rate_limit_key(caller_id: str) -> str:
    return f"poster:ratelimit:{caller_id}"


def active_jobs_key(caller_id: str) -> str:
    return f"poster:active_jobs:{caller_id}"
