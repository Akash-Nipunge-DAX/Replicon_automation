"""Fill template persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import FillTemplate, TemplateTask


class TemplateRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_for_user(self, user_id: int) -> list[FillTemplate]:
        stmt = (
            select(FillTemplate)
            .where(FillTemplate.user_id == user_id)
            .options(selectinload(FillTemplate.tasks))
            .order_by(FillTemplate.id)
        )
        return list(self._db.scalars(stmt).unique().all())

    def get_for_user(self, user_id: int, template_id: int) -> FillTemplate | None:
        stmt = (
            select(FillTemplate)
            .where(FillTemplate.user_id == user_id, FillTemplate.id == template_id)
            .options(selectinload(FillTemplate.tasks))
        )
        return self._db.scalars(stmt).first()

    def get_default(self, user_id: int) -> FillTemplate | None:
        stmt = (
            select(FillTemplate)
            .where(FillTemplate.user_id == user_id, FillTemplate.is_default.is_(True))
            .options(selectinload(FillTemplate.tasks))
        )
        return self._db.scalars(stmt).first()

    def create(
        self,
        *,
        user_id: int,
        name: str,
        skip_weekends: bool,
        skip_holidays: bool,
        submit_after_fill: bool,
        is_default: bool,
        tasks: list[tuple[str, float]],
    ) -> FillTemplate:
        if is_default:
            self._clear_default(user_id)
        template = FillTemplate(
            user_id=user_id,
            name=name.strip(),
            skip_weekends=skip_weekends,
            skip_holidays=skip_holidays,
            submit_after_fill=submit_after_fill,
            is_default=is_default,
        )
        self._db.add(template)
        self._db.flush()
        for i, (task_name, hours) in enumerate(tasks):
            self._db.add(
                TemplateTask(
                    template_id=template.id,
                    task_name=task_name.strip(),
                    hours=hours,
                    sort_order=i,
                )
            )
        self._db.flush()
        return self.get_for_user(user_id, template.id)  # type: ignore[return-value]

    def update(
        self,
        template: FillTemplate,
        *,
        name: str,
        skip_weekends: bool,
        skip_holidays: bool,
        submit_after_fill: bool,
        is_default: bool,
        tasks: list[tuple[str, float]],
    ) -> FillTemplate:
        if is_default:
            self._clear_default(template.user_id)
        template.name = name.strip()
        template.skip_weekends = skip_weekends
        template.skip_holidays = skip_holidays
        template.submit_after_fill = submit_after_fill
        template.is_default = is_default
        for existing in list(template.tasks):
            self._db.delete(existing)
        self._db.flush()
        for i, (task_name, hours) in enumerate(tasks):
            self._db.add(
                TemplateTask(
                    template_id=template.id,
                    task_name=task_name.strip(),
                    hours=hours,
                    sort_order=i,
                )
            )
        self._db.flush()
        return self.get_for_user(template.user_id, template.id)  # type: ignore[return-value]

    def delete(self, template: FillTemplate) -> None:
        self._db.delete(template)
        self._db.flush()

    def _clear_default(self, user_id: int) -> None:
        for t in self.list_for_user(user_id):
            if t.is_default:
                t.is_default = False
        self._db.flush()

    def ensure_default_seed(self, user_id: int) -> FillTemplate:
        """Seed 'Default 9h' if the user has no templates yet."""
        existing = self.list_for_user(user_id)
        if existing:
            default = next((t for t in existing if t.is_default), existing[0])
            return default
        return self.create(
            user_id=user_id,
            name="Default 9h",
            skip_weekends=True,
            skip_holidays=True,
            submit_after_fill=True,
            is_default=True,
            tasks=[("Coding", 3.0), ("Management", 3.0), ("Meetings", 3.0)],
        )
