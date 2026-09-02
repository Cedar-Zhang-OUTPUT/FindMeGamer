"""Narrow persisted Template projections shared with Outreach services."""

from app.db.models.outreach import Template
from app.schemas.outreach import TemplateData


def template_data_from_row(row: Template) -> TemplateData:
    """Project one Template row into the immutable renderer input."""

    if not isinstance(row, Template):
        raise TypeError("row must be a Template")
    return TemplateData(
        subject_template=row.subject_template,
        body_markdown=row.body_markdown,
        accepted_label=row.accepted_label,
        declined_label=row.declined_label,
    )


__all__ = ["template_data_from_row"]
