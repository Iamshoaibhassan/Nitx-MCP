from fastapi import APIRouter, Depends

from src.auth import enforce_rate_limit
from src.models import TemplateListResponse
from src.services import TemplateService

router = APIRouter(prefix="/templates", dependencies=[Depends(enforce_rate_limit)])


def get_template_service() -> TemplateService:
    return TemplateService()


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    category: str | None = None,
    search: str | None = None,
    service: TemplateService = Depends(get_template_service),
) -> TemplateListResponse:
    templates = service.list_templates(category=category, search=search)
    return TemplateListResponse(templates=templates)
