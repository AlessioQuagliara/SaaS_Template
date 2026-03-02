# =============================================================================
# backend/app/routes/auth/auth.py
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Form, Request, status, Depends, HTTPException, Response

from fastapi.responses import HTMLResponse, RedirectResponse

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import templates

from app.core.database import get_db

from app.core.sicurezza import verifica_password_async

from app.models import Utente, Tenant

router = APIRouter()


# -----------------------------------------------------------------------------
# LOGIN -----------------------------------------------------------------------
# -----------------------------------------------------------------------------


# | -- Render pagina -----------------------------------------
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str | None = None):
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "next": next or "/"},
    )


# | -- Azione Login -----------------------------------------
@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: AsyncSession = Depends(get_db),
):


    # ---- Trova utente attivo per email ----------------------
    risultato = await db.execute(
        select(Utente).where(
            Utente.email == email,
            Utente.attivo.is_(True),
        )
    )


    utente = risultato.scalar_one_or_none()


    # ---- Verifica password ----------------------------------
    if utente is None or not verifica_password_async(password, utente.hashed_password):
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "next": next,
                "error": "Credenziali non valide",
            },
            status_code=400,
        )


    # ---- Carica tenant dell'utente --------------------------
    risultato_tenant = await db.execute(
        select(Tenant).where(
            Tenant.id == utente.tenant_id,
            Tenant.attivo.is_(True),
        )
    )


    tenant = risultato_tenant.scalar_one_or_none()


    # ---- Verifica tenant -----------------------------------
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant associato all'utente cancellato o non valido",
        )


    # ---- Costruisci URL di redirect ------------------------
    # next "/" è il default del form, non una destinazione reale
    redirect_url = next if next and next != "/" else f"/{tenant.slug}/admin/dashboard"


    # ---- Richiesta HTMX: usa HX-Redirect -------------------
    if request.headers.get("HX-Request") == "true":
        risposta = Response(status_code=204)
        risposta.set_cookie(
            "id_sessione_utente",
            str(utente.id),
            httponly=True,
            secure=False,  # In produzione: True con HTTPS
            samesite="lax",
        )
        risposta.headers["HX-Redirect"] = redirect_url
        return risposta


    # ---- Richiesta normale: redirect 303 -------------------
    risposta = RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )


    risposta.set_cookie(
        "id_sessione_utente",
        str(utente.id),
        httponly=True,
        secure=False,  # In produzione mettere True per HTTPS
        samesite="lax",
    )


    return risposta


# -----------------------------------------------------------------------------
# LOGOUT
# -----------------------------------------------------------------------------

@router.post("/logout")
async def logout_submit():
    risposta = RedirectResponse(
        url="/auth/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )

    risposta.delete_cookie("id_sessione_utente")  
    return risposta



# -----------------------------------------------------------------------------
# SIGN-UP (registrazione)
# -----------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("auth/register.html", {"request": request})


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if password != password2:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Le password non coincidono"},
            status_code=400,
        )

    # TODO: create user + send verification email (async job)
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# PASSWORD RECOVERY (richiesta reset)
# -----------------------------------------------------------------------------

@router.get("/password-recovery", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {"request": request})


@router.post("/password-recovery", response_class=HTMLResponse)
async def forgot_password_submit(request: Request, email: str = Form(...)):
    # TODO: generate token + send email (async job)
    # Security: always neutral response
    return templates.TemplateResponse(
        "auth/forgot_password.html",
        {"request": request, "ok": "Se l’email esiste, riceverai un link di reset."},
    )


# -----------------------------------------------------------------------------
# RESET PASSWORD (con token)
# -----------------------------------------------------------------------------

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str):
    return templates.TemplateResponse(
        "auth/reset_password.html",
        {"request": request, "token": token},
    )


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if password != password2:
        return templates.TemplateResponse(
            "auth/reset_password.html",
            {"request": request, "token": token, "error": "Le password non coincidono"},
            status_code=400,
        )

    # TODO: validate token + change password
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# CONFIRM PASSWORD (reauth)
# -----------------------------------------------------------------------------

@router.get("/confirm-password", response_class=HTMLResponse)
async def confirm_password_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        "auth/confirm_password.html",
        {"request": request, "next": next},
    )


@router.post("/confirm-password", response_class=HTMLResponse)
async def confirm_password_submit(
    request: Request,
    password: str = Form(...),
    next: str = Form("/"),
):
    # TODO: verify current user's password
    ok = (password == "demo")

    if not ok:
        return templates.TemplateResponse(
            "auth/confirm_password.html",
            {"request": request, "next": next, "error": "Password errata"},
            status_code=400,
        )

    return RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# 2FA (TOTP)
# -----------------------------------------------------------------------------

@router.get("/2fa", response_class=HTMLResponse)
async def two_factor_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        "auth/two_factor.html",
        {"request": request, "next": next},
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
            "auth/two_factor.html",
            {"request": request, "next": next, "error": "Codice non valido"},
            status_code=400,
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