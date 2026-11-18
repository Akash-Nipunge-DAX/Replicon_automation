"""Register / login / logout (session cookie)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_optional_user
from app.services.auth_service import AuthError, AuthService
from app.web.templating import templates

router = APIRouter(tags=["auth"])


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user=Depends(get_optional_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/register.html",
        {"error": None},
    )


@router.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "Passwords do not match."},
            status_code=400,
        )
    try:
        user = AuthService(db).register(username, password)
    except AuthError as exc:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": exc.message},
            status_code=400,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/setup", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user=Depends(get_optional_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": None},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user = AuthService(db).authenticate(username, password)
    except AuthError as exc:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": exc.message},
            status_code=400,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/logout")
def logout_get(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
