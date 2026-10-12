from src.models import Template, TemplateCategory

_TEMPLATES: list[Template] = [
    Template(id="tpl-001", name="Grand Opening Banner", category=TemplateCategory.EVENT),
    Template(id="tpl-002", name="Holiday Sale Blast", category=TemplateCategory.SALE),
    Template(id="tpl-003", name="New Arrival Spotlight", category=TemplateCategory.PRODUCT),
    Template(id="tpl-004", name="Flash Discount Flyer", category=TemplateCategory.SALE),
    Template(id="tpl-005", name="Instagram Product Teaser", category=TemplateCategory.SOCIAL),
    Template(id="tpl-006", name="Open House Invitation", category=TemplateCategory.REAL_ESTATE),
    Template(id="tpl-007", name="Weekend Brunch Special", category=TemplateCategory.RESTAURANT),
    Template(id="tpl-008", name="Product Launch Teaser", category=TemplateCategory.PRODUCT),
    Template(id="tpl-009", name="Conference Save-the-Date", category=TemplateCategory.EVENT),
    Template(id="tpl-010", name="Story Highlight Card", category=TemplateCategory.SOCIAL),
]


class TemplateService:
    def list_templates(self, category: str | None = None, search: str | None = None) -> list[Template]:
        results = _TEMPLATES

        if category:
            normalized = category.strip().lower()
            results = [t for t in results if t.category.value == normalized]

        if search:
            normalized_search = search.strip().lower()
            results = [t for t in results if normalized_search in t.name.lower()]

        return results
