from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import JobStatus, Resolution, TemplateCategory

MAX_IMAGE_FIELD_LENGTH = 5_000_000


class Template(BaseModel):
    id: str
    name: str
    category: TemplateCategory


class TemplateListResponse(BaseModel):
    templates: list[Template]


class CreatePosterJobRequest(BaseModel):
    template_id: str | None = Field(default=None, max_length=100)
    product_image: str = Field(..., min_length=1, max_length=MAX_IMAGE_FIELD_LENGTH)
    background_image: str = Field(..., min_length=1, max_length=MAX_IMAGE_FIELD_LENGTH)
    prompt: str = Field(..., min_length=1, max_length=500)
    image_count: int = Field(..., ge=1, le=4)
    resolution: Resolution
    idempotency_key: str | None = Field(default=None, max_length=200)


class CreatePosterJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class GeneratedImage(BaseModel):
    id: str
    url: str
    resolution: Resolution


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    images: list[GeneratedImage] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class CancelJobResponse(BaseModel):
    job_id: str
    status: JobStatus
