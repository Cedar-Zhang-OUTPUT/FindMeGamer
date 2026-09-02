"""Persistence operations for shared Outreach Templates."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.outreach import Template
from app.schemas.outreach import TemplateData


_TEMPLATE_MUTATION_LOCK_ID = 0x464D4754454D504C


class TemplateNameConflictError(ValueError):
    """A current Template already has the requested display name."""


class LastTemplateError(ValueError):
    """The final Template cannot be deleted."""


class DefaultTemplateDeleteError(ValueError):
    """The current default must be replaced before deletion."""


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


class OutreachRepository:
    def __init__(self, database_session: Session) -> None:
        self._session = database_session

    def list_templates(self) -> list[Template]:
        return list(
            self._session.scalars(
                select(Template).order_by(
                    Template.is_default.desc(),
                    func.lower(Template.name),
                    Template.id,
                )
            ).all()
        )

    def get_template(self, template_id: UUID) -> Template | None:
        return self._session.get(Template, template_id)

    def get_template_for_mutation(self, template_id: UUID) -> Template | None:
        self.lock_template_mutations()
        return self._session.get(Template, template_id, populate_existing=True)

    def lock_template_mutations(self) -> None:
        self._session.execute(
            select(func.pg_advisory_xact_lock(_TEMPLATE_MUTATION_LOCK_ID))
        )

    def _name_is_available(self, name: str, *, excluding: UUID | None = None) -> bool:
        normalized = name.casefold()
        return all(
            row.id == excluding or row.name.casefold() != normalized
            for row in self._session.scalars(select(Template)).all()
        )

    def create_template(self, values: Mapping[str, str]) -> Template:
        self.lock_template_mutations()
        name = values["name"]
        if not self._name_is_available(name):
            raise TemplateNameConflictError
        is_first = self._session.scalar(select(func.count()).select_from(Template)) == 0
        row = Template(
            name=name,
            version=1,
            subject_template=values["subject_template"],
            body_markdown=values["body_markdown"],
            accepted_label=values["accepted_label"],
            declined_label=values["declined_label"],
            is_default=is_first,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update_template(self, row: Template, values: Mapping[str, str]) -> Template:
        self.lock_template_mutations()
        requested_name = values.get("name", row.name)
        if not self._name_is_available(requested_name, excluding=row.id):
            raise TemplateNameConflictError
        changed = False
        for field, value in values.items():
            if getattr(row, field) != value:
                setattr(row, field, value)
                changed = True
        if changed:
            row.version += 1
            self._session.flush()
        return row

    def duplicate_template(self, source: Template) -> Template:
        self.lock_template_mutations()
        existing_names = {
            row.name.casefold() for row in self._session.scalars(select(Template)).all()
        }
        sequence = 1
        while True:
            suffix = " Copy" if sequence == 1 else f" Copy {sequence}"
            name = f"{source.name[: 255 - len(suffix)]}{suffix}"
            if name.casefold() not in existing_names:
                break
            sequence += 1
        duplicate = Template(
            name=name,
            version=1,
            subject_template=source.subject_template,
            body_markdown=source.body_markdown,
            accepted_label=source.accepted_label,
            declined_label=source.declined_label,
            is_default=False,
        )
        self._session.add(duplicate)
        self._session.flush()
        return duplicate

    def set_default_template(self, selected: Template) -> Template:
        self.lock_template_mutations()
        if selected.is_default:
            return selected
        for row in self._session.scalars(
            select(Template).where(Template.is_default.is_(True))
        ).all():
            row.is_default = False
        self._session.flush()
        selected.is_default = True
        self._session.flush()
        return selected

    def delete_template(self, row: Template) -> None:
        self.lock_template_mutations()
        count = self._session.scalar(select(func.count()).select_from(Template))
        if count == 1:
            raise LastTemplateError
        if row.is_default:
            raise DefaultTemplateDeleteError
        self._session.delete(row)
        self._session.flush()


__all__ = [
    "DefaultTemplateDeleteError",
    "LastTemplateError",
    "OutreachRepository",
    "TemplateNameConflictError",
    "template_data_from_row",
]
