"""Fill-run history persistence."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import FillRun


class FillRunRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_for_user(self, user_id: int, *, limit: int = 50) -> list[FillRun]:
        stmt = (
            select(FillRun)
            .where(FillRun.user_id == user_id)
            .options(selectinload(FillRun.template))
            .order_by(FillRun.id.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).unique().all())

    def create(
        self,
        *,
        user_id: int,
        template_id: int | None,
        week_date: str,
        status: str,
        summary: dict[str, Any],
    ) -> FillRun:
        run = FillRun(
            user_id=user_id,
            template_id=template_id,
            week_date=week_date,
            status=status,
            summary_json=json.dumps(summary, default=str),
        )
        self._db.add(run)
        self._db.flush()
        return run
