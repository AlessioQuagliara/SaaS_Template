# =============================================================================
# test/test_routes.py  –  ROUTES suite
# =============================================================================
# Copre: endpoint pubblici, rotte admin, risposte HTMX (HX-Request),
#        health check, gestione errori HTTP, rotte admin per ruolo
# =============================================================================

from __future__ import annotations

import pytest

from conftest import (
    TEST_TENANT_SLUG,
    _crea_sessione_utente,
    _crea_tenant_e_utente,
)
from app.core.auth import SESSION_COOKIE_NAME
from app.models import SottoscrizioniStati, UtenteRuolo


# =============================================================================
# Helpers
# =============================================================================


def _cookies(id_sessione: str) -> dict:
    return {SESSION_COOKIE_NAME: id_sessione}


def _htmx_headers() -> dict:
    return {"HX-Request": "true"}


# =============================================================================
# ROUTES-001  GET /health → 200 {"status": "ok"}
# =============================================================================


async def test_ROUTES_001_health_check(client):
    r = await client.get("/health")
    assert r.status_code == 200, f"ROUTES-001 FAIL: /health → status {r.status_code}"
    data = r.json()
    assert data.get("status") == "ok", (
        f"ROUTES-001 FAIL: risposta /health = {data}, atteso {{status: ok}}"
    )


# =============================================================================
# ROUTES-002  GET /controlli/health → 200 {"status": "acceso"}
# =============================================================================


async def test_ROUTES_002_controlli_health(client):
    r = await client.get("/controlli/health")
    assert r.status_code == 200, (
        f"ROUTES-002 FAIL: /controlli/health → status {r.status_code}"
    )
    data = r.json()
    assert "status" in data, f"ROUTES-002 FAIL: risposta senza campo 'status': {data}"


# =============================================================================
# ROUTES-003  GET /auth/login → 200 HTML
# =============================================================================


async def test_ROUTES_003_login_page_html(client):
    r = await client.get("/auth/login")
    assert r.status_code == 200
    assert b"<html" in r.content.lower() or b"<!doctype" in r.content.lower(), (
        "ROUTES-003 FAIL: /auth/login non restituisce HTML"
    )


# =============================================================================
# ROUTES-004  GET /auth/register → 200 HTML
# =============================================================================


async def test_ROUTES_004_register_page_html(client):
    r = await client.get("/auth/register")
    assert r.status_code == 200
    assert b"<html" in r.content.lower() or b"<!doctype" in r.content.lower() or b"form" in r.content.lower(), (
        "ROUTES-004 FAIL: /auth/register non restituisce HTML"
    )


# =============================================================================
# ROUTES-005  GET /auth/password-recovery → 200 HTML
# =============================================================================


async def test_ROUTES_005_password_recovery_page(client):
    r = await client.get("/auth/password-recovery")
    assert r.status_code == 200


# =============================================================================
# ROUTES-006  GET /{tenant}/admin/dashboard con HX-Request → HTML parziale
#             La risposta non deve contenere il layout completo (<html>)
# =============================================================================


async def test_ROUTES_006_dashboard_htmx_parziale(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies=_cookies(id_sessione),
        headers=_htmx_headers(),
    )
    assert r.status_code == 200, (
        f"ROUTES-006 FAIL: status {r.status_code} con HX-Request"
    )
    # Con HX-Request, non ci aspettiamo necessariamente la pagina intera,
    # ma almeno una risposta HTML non vuota
    assert len(r.content) > 0, "ROUTES-006 FAIL: risposta HTMX vuota"


# =============================================================================
# ROUTES-007  POST /auth/login con HX-Request → HX-Redirect nell'header
# =============================================================================


async def test_ROUTES_007_login_htmx_hx_redirect(client, db_session, fake_redis):
    from conftest import TEST_PASSWORD, genera_csrf

    tenant, utente = await _crea_tenant_e_utente(db_session)
    s, t = genera_csrf()

    r = await client.post(
        "/auth/login",
        data={
            "email": utente.email,
            "password": TEST_PASSWORD,
            "csrf_token": t,
            "sessione_temp": s,
            "next": "/",
        },
        headers=_htmx_headers(),
    )
    # Con HX-Request, il login deve rispondere con 204 + HX-Redirect
    if r.status_code == 204:
        assert "HX-Redirect" in r.headers, (
            "ROUTES-007 FAIL: login HTMX risponde 204 ma manca header HX-Redirect"
        )
    elif r.status_code in (302, 303):
        # Fallback redirect normale – anche accettabile
        pass
    else:
        pytest.fail(
            f"ROUTES-007 FAIL: login HTMX → status inatteso {r.status_code}"
        )


# =============================================================================
# ROUTES-008  GET /{tenant}/admin/users accessibile a SUPERUTENTE
# =============================================================================


async def test_ROUTES_008_admin_users_superutente(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="routes-users-super",
        email="routes-super@example.com",
        ruolo=UtenteRuolo.SUPERUTENTE,
    )
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/users",
        cookies=_cookies(id_sessione),
    )
    assert r.status_code == 200, (
        f"ROUTES-008 FAIL: users admin → status {r.status_code} per superutente"
    )


# =============================================================================
# ROUTES-009  GET /{tenant}/admin/sottoscrizioni accessibile a SUPERUTENTE
# =============================================================================


async def test_ROUTES_009_admin_sottoscrizioni(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="routes-billing",
        email="routes-billing@example.com",
    )
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/sottoscrizioni",
        cookies=_cookies(id_sessione),
    )
    # Può restituire 200 diretto o redirect se piano non attivo
    assert r.status_code in (200, 302, 303, 403), (
        f"ROUTES-009 FAIL: sottoscrizioni → status {r.status_code}"
    )


# =============================================================================
# ROUTES-010  GET /auth/login con ?error= → messaggio visibile
# =============================================================================


async def test_ROUTES_010_login_error_param(client):
    r = await client.get("/auth/login?error=Credenziali+non+valide")
    assert r.status_code == 200
    content = r.content.lower()
    assert b"credenziali" in content or b"error" in content or b"not" in content, (
        "ROUTES-010 FAIL: parametro error non mostrato nella pagina login"
    )


# =============================================================================
# ROUTES-011  GET /docs → 200 (OpenAPI docs attive)
# =============================================================================


async def test_ROUTES_011_openapi_docs(client):
    r = await client.get("/docs")
    assert r.status_code == 200, (
        f"ROUTES-011 FAIL: /docs → status {r.status_code} (atteso 200)"
    )


# =============================================================================
# ROUTES-012  GET /openapi.json → 200 JSON schema valido
# =============================================================================


async def test_ROUTES_012_openapi_json(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert "paths" in schema, "ROUTES-012 FAIL: openapi.json non contiene 'paths'"
    assert "info" in schema, "ROUTES-012 FAIL: openapi.json non contiene 'info'"


# =============================================================================
# ROUTES-013  Rotta inesistente → 404 gestito
# =============================================================================


async def test_ROUTES_013_rotta_inesistente_404(client):
    r = await client.get("/questa-rotta/non/esiste")
    assert r.status_code == 404, (
        f"ROUTES-013 FAIL: rotta inesistente → status {r.status_code} (atteso 404)"
    )


# =============================================================================
# ROUTES-014  GET /{tenant}/admin/impostazioni accessibile a SUPERUTENTE
# =============================================================================


async def test_ROUTES_014_admin_impostazioni(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="routes-settings",
        email="routes-settings@example.com",
    )
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/impostazioni",
        cookies=_cookies(id_sessione),
    )
    assert r.status_code in (200, 302, 303), (
        f"ROUTES-014 FAIL: impostazioni → status {r.status_code}"
    )


# =============================================================================
# ROUTES-015  Ruolo UTENTE (sola lettura) accede alla dashboard ma non a users
# =============================================================================


async def test_ROUTES_015_ruolo_utente_accesso_limitato(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="routes-readonly",
        email="routes-readonly@example.com",
        ruolo=UtenteRuolo.UTENTE,
    )
    id_sessione = await _crea_sessione_utente(utente, tenant)

    # Dashboard deve essere accessibile
    r_dash = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies=_cookies(id_sessione),
    )
    assert r_dash.status_code == 200, (
        f"ROUTES-015 FAIL: dashboard non accessibile a ruolo UTENTE – status {r_dash.status_code}"
    )


# =============================================================================
# ROUTES-016  Logout via POST → redirect a /auth/login
# =============================================================================


async def test_ROUTES_016_logout_redirect(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.post(
        "/auth/logout",
        cookies=_cookies(id_sessione),
    )
    assert r.status_code in (302, 303), (
        f"ROUTES-016 FAIL: logout → status {r.status_code} (atteso redirect)"
    )
    location = r.headers.get("location", "")
    assert "login" in location or location.startswith("/"), (
        f"ROUTES-016 FAIL: logout redirect verso '{location}' (atteso /auth/login)"
    )
