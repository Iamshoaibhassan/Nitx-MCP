from src.utils import ENV


class Settings:
    def __init__(self) -> None:
        self.app_name = ENV["APP_NAME"]
        self.host = ENV["HOST"]
        self.port = int(ENV["PORT"])
        self.log_level = ENV["LOG_LEVEL"]

        self.api_key = ENV["API_KEY"]

        self.redis_host = ENV["REDIS_HOST"]
        self.redis_port = int(ENV["REDIS_PORT"])
        self.redis_db = int(ENV["REDIS_DB"])

        self.idempotency_ttl_seconds = int(ENV["IDEMPOTENCY_TTL_SECONDS"])
        self.job_record_ttl_seconds = int(ENV["JOB_RECORD_TTL_SECONDS"])

        self.job_min_duration_seconds = float(ENV["JOB_MIN_DURATION_SECONDS"])
        self.job_max_duration_seconds = float(ENV["JOB_MAX_DURATION_SECONDS"])
        self.job_failure_rate = float(ENV["JOB_FAILURE_RATE"])
        self.job_poll_interval_seconds = float(ENV["JOB_POLL_INTERVAL_SECONDS"])
        self.job_stale_claim_seconds = int(ENV["JOB_STALE_CLAIM_SECONDS"])

        self.max_prompt_length = int(ENV["MAX_PROMPT_LENGTH"])
        self.min_image_count = int(ENV["MIN_IMAGE_COUNT"])
        self.max_image_count = int(ENV["MAX_IMAGE_COUNT"])

        self.rate_limit_requests_per_window = int(ENV["RATE_LIMIT_REQUESTS_PER_WINDOW"])
        self.rate_limit_window_seconds = int(ENV["RATE_LIMIT_WINDOW_SECONDS"])
        self.max_concurrent_jobs_per_key = int(ENV["MAX_CONCURRENT_JOBS_PER_KEY"])

        self.mcp_backend_base_url = ENV["MCP_BACKEND_BASE_URL"]
        self.mcp_http_timeout_seconds = float(ENV["MCP_HTTP_TIMEOUT_SECONDS"])
        self.mcp_http_max_retries = int(ENV["MCP_HTTP_MAX_RETRIES"])


def get_settings() -> Settings:
    return Settings()
