from enum import StrEnum


class JobStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Resolution(StrEnum):
    ONE_K = "1k"
    TWO_K = "2k"


class TemplateCategory(StrEnum):
    EVENT = "event"
    PRODUCT = "product"
    SALE = "sale"
    SOCIAL = "social"
    REAL_ESTATE = "real_estate"
    RESTAURANT = "restaurant"
