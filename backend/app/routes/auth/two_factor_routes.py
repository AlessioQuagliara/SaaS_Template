# =============================================================================
# backend/app/routes/auth/two_factor_routes.py
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Form, Request, status

from fastapi.responses import HTMLResponse, RedirectResponse

from app.core import templates

router = APIRouter()


@router.get("/2fa", response_class=HTMLResponse)
async def two_factor_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        request,
        "auth/two_factor.html",
        {"next": next},
    )


@router.post("/2fa", response_class=HTMLResponse)
async def two_factor_submit(
    request: Request,
    code: str = Form(...),
    next: str = Form("/"),
):
    # TODO: validate TOTP code
    ok = (code == "123456")

    if not ok:
        return templates.TemplateResponse(
            request,
            "auth/two_factor.html",
            {"next": next, "error": "Codice non valido"},
            status_code=200,
        )

    resp = RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        "session",
        "fake-session-token",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return resp
