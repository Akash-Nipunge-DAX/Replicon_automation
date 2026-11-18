"""Fill template CRUD (server-rendered)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.dependencies import get_current_user
from app.repositories.credential_repository import CredentialRepository
from app.repositories.template_repository import TemplateRepository
from app.web.templating import templates

router = APIRouter(prefix="/templates", tags=["templates"])

def _require_configured(user: User, db: Session) -> RedirectResponse | None:
    if CredentialRepository(db).get_for_user(user.id) is None:
        return RedirectResponse("/setup", status_code=303)
    return None


def _parse_tasks(
    task_names: list[str],
    task_hours: list[str],
) -> list[tuple[str, float]]:
    tasks: list[tuple[str, float]] = []
    for name, hours in zip(task_names, task_hours, strict=False):
        name = (name or "").strip()
        if not name:
            continue
        try:
            h = float(hours)
        except (TypeError, ValueError):
            continue
        if h <= 0:
            continue
        tasks.append((name, h))
    return tasks


@router.get("", response_class=HTMLResponse)
def list_templates(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    redirect = _require_configured(user, db)
    if redirect:
        return redirect
    repo = TemplateRepository(db)
    items = repo.list_for_user(user.id)
    if not items:
        repo.ensure_default_seed(user.id)
        items = repo.list_for_user(user.id)
    return templates.TemplateResponse(
        request,
        "templates/list.html",
        {"user": user, "templates": items, "flash": request.session.pop("flash", None)},
    )


@router.get("/new", response_class=HTMLResponse)
def new_template_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    redirect = _require_configured(user, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "templates/edit.html",
        {
            "user": user,
            "template": None,
            "tasks": [("Coding", 3.0), ("Management", 3.0), ("Meetings", 3.0)],
            "error": None,
        },
    )


def _flag(value: str | None) -> bool:
    return (value or "").lower() in {"true", "1", "on", "yes"}


@router.post("/new")
def create_template(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    skip_weekends: str | None = Form(None),
    skip_holidays: str | None = Form(None),
    submit_after_fill: str | None = Form(None),
    is_default: str | None = Form(None),
    task_name: list[str] = Form([]),
    task_hours: list[str] = Form([]),
):
    tasks = _parse_tasks(task_name, task_hours)
    if not tasks:
        return templates.TemplateResponse(
            request,
            "templates/edit.html",
            {
                "user": user,
                "template": None,
                "tasks": [("Coding", 3.0)],
                "error": "Add at least one task with hours > 0.",
            },
            status_code=400,
        )
    TemplateRepository(db).create(
        user_id=user.id,
        name=name,
        skip_weekends=_flag(skip_weekends),
        skip_holidays=_flag(skip_holidays),
        submit_after_fill=_flag(submit_after_fill),
        is_default=_flag(is_default),
        tasks=tasks,
    )
    request.session["flash"] = "Template created."
    return RedirectResponse("/templates", status_code=303)


@router.get("/{template_id}", response_class=HTMLResponse)
def edit_template_page(
    template_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    redirect = _require_configured(user, db)
    if redirect:
        return redirect
    template = TemplateRepository(db).get_for_user(user.id, template_id)
    if template is None:
        return RedirectResponse("/templates", status_code=303)
    tasks = [(t.task_name, t.hours) for t in template.tasks] or [("Coding", 3.0)]
    return templates.TemplateResponse(
        request,
        "templates/edit.html",
        {"user": user, "template": template, "tasks": tasks, "error": None},
    )


@router.post("/{template_id}")
def update_template(
    template_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    skip_weekends: str | None = Form(None),
    skip_holidays: str | None = Form(None),
    submit_after_fill: str | None = Form(None),
    is_default: str | None = Form(None),
    task_name: list[str] = Form([]),
    task_hours: list[str] = Form([]),
):
    repo = TemplateRepository(db)
    template = repo.get_for_user(user.id, template_id)
    if template is None:
        return RedirectResponse("/templates", status_code=303)
    tasks = _parse_tasks(task_name, task_hours)
    if not tasks:
        return templates.TemplateResponse(
            request,
            "templates/edit.html",
            {
                "user": user,
                "template": template,
                "tasks": [(t.task_name, t.hours) for t in template.tasks],
                "error": "Add at least one task with hours > 0.",
            },
            status_code=400,
        )
    repo.update(
        template,
        name=name,
        skip_weekends=_flag(skip_weekends),
        skip_holidays=_flag(skip_holidays),
        submit_after_fill=_flag(submit_after_fill),
        is_default=_flag(is_default),
        tasks=tasks,
    )
    request.session["flash"] = "Template saved."
    return RedirectResponse("/templates", status_code=303)


@router.post("/{template_id}/delete")
def delete_template(
    template_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = TemplateRepository(db)
    template = repo.get_for_user(user.id, template_id)
    if template is not None:
        repo.delete(template)
        request.session["flash"] = "Template deleted."
    return RedirectResponse("/templates", status_code=303)
