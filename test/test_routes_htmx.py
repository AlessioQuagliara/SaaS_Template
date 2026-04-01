# =============================================================================
# test/test_routes_htmx.py  –  ROUTES / HTMX suite
# =============================================================================
# Copre: health route, auth routes, admin routes, HX-Request, webhook route,
#        headers sicurezza e comportamenti redirect/fragment
# =============================================================================

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from conftest import (
    TEST_PASSWORD,
    _crea_tenant_e_utente,
    _crea_sessione_utente,
    genera_csrf,
)
from app.core.auth import SESSION_COOKIE_NAME


# =============================================================================
# ROUTES-001  GET /health -> 200 {status: ok}
# =============================================================================


async def test_ROUTES_001_health_main(client):
    r = await client.get("/health")
    assert r.status_code == 200, (
        f"ROUTES-001 FAIL: status {r.status_code} su /health"
    )
    body = r.json()
    assert body.get("status") in ("ok", "acceso"), (
        f"ROUTES-001 FAIL: payload inatteso {body}"
    )


# =============================================================================
# ROUTES-002  GET /controlli/health -> 200
# =============================================================================


async def test_ROUTES_002_health_controlli(client):
    r = await client.get("/controlli/health")
    assert r.status_code == 200, (
        f"ROUTES-002 FAIL: status {r.status_code} su /controlli/health"
    )
    body = r.json()
    assert "status" in body, "ROUTES-002 FAIL: risposta health senza chiave 'status'"


# =============================================================================
# ROUTES-003  GET /auth/login con HX-Request
# =============================================================================


async def test_ROUTES_003_auth_login_hx_get(client):
    r = await client.get("/auth/login", headers={"HX-Request": "true"})
    assert r.status_code == 200
    # Anche in HX-Request, il template deve contenere i campi form principali
    content = r.content.lower()
    assert b"csrf" in content or b"login" in content, (
        "ROUTES-003 FAIL: risposta login HTMX senza contenuto atteso"
    )


# =============================================================================
# ROUTES-004  POST /auth/login con HX-Request -> 204 + HX-Redirect
# =============================================================================


async def test_ROUTES_004_login_hx_post_redirect_header(client, db_session, fake_redis):
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
        headers={"HX-Request": "true"},
    )

    assert r.status_code in (204, 200), (
        f"ROUTES-004 FAIL: login HTMX status {r.status_code}"
    )
    if r.status_code == 204:
        assert "HX-Redirect" in r.headers, (
            "ROUTES-004 FAIL: login HTMX 204 senza header HX-Redirect"
        )


# =============================================================================
# ROUTES-005  GET /auth/register -> 200 con CSRF
# =============================================================================


async def test_ROUTES_005_register_page(client):
    r = await client.get("/auth/register")
    assert r.status_code == 200
    content = r.content.lower()
    assert b"csrf" in content or b"register" in content or b"registr" in content, (
        "ROUTES-005 FAIL: pagina register senza elementi attesi"
    )


# =============================================================================
# ROUTES-006  GET /auth/password-recovery -> 200
# =============================================================================


async def test_ROUTES_006_password_recovery_page(client):
    r = await client.get("/auth/password-recovery")
    assert r.status_code == 200, (
        f"ROUTES-006 FAIL: status {r.status_code} su /auth/password-recovery"
    )


# =============================================================================
# ROUTES-007  GET dashboard senza cookie -> non autorizzato
# =============================================================================


async def test_ROUTES_007_dashboard_no_cookie(client):
    r = await client.get("/tenant-qualsiasi/admin/dashboard")
    assert r.status_code in (401, 302, 303, 404), (
        f"ROUTES-007 FAIL: dashboard senza cookie status inatteso {r.status_code}"
    )


# =============================================================================
# ROUTES-008  GET dashboard con cookie valido -> 200
# =============================================================================


async def test_ROUTES_008_dashboard_cookie_valido(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies={SESSION_COOKIE_NAME: id_sessione},
    )
    assert r.status_code == 200, (
        f"ROUTES-008 FAIL: dashboard con cookie valido -> status {r.status_code}"
    )


# =============================================================================
# ROUTES-009  GET /docs è disponibile in ambiente dev
# =============================================================================


async def test_ROUTES_009_docs_accessibile(client):
    r = await client.get("/docs")
    assert r.status_code == 200, (
        f"ROUTES-009 FAIL: /docs non accessibile (status {r.status_code})"
    )


# =============================================================================
# ROUTES-010  Webhook stripe senza secret configurato -> 503
# =============================================================================


async def test_ROUTES_010_stripe_webhook_secret_missing(client):
    with patch("app.core.config.settings.stripe_webhook_secret", ""):
        r = await client.post(
            "/stripe/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "t=1,v1=fake", "Content-Type": "application/json"},
        )
    assert r.status_code == 503, (
        f"ROUTES-010 FAIL: webhook senza secret -> status {r.status_code}, atteso 503"
    )


# =============================================================================
# ROUTES-011  Webhook stripe event sconosciuto -> 200/204 (ack)
# =============================================================================


async def test_ROUTES_011_stripe_webhook_unknown_event_ack(client):
    event = MagicMock()
    event.type = "radom.event.unhandled"
    event.data = MagicMock()
    event.data.object = {"id": "obj_1"}

    with (
        patch("app.routes.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.core.config.settings.stripe_webhook_secret", "whsec_test123"),
    ):
        r = await client.post(
            "/stripe/webhook",
            content=b'{"id":"evt_123","type":"random.event"}',
            headers={"Stripe-Signature": "t=1,v1=fake", "Content-Type": "application/json"},
        )

    assert r.status_code in (200, 204), (
        f"ROUTES-011 FAIL: event sconosciuto non ackato, status {r.status_code}"
    )


# =============================================================================
# ROUTES-012  Header di sicurezza base (hard-check)
# =============================================================================


async def test_ROUTES_012_security_headers_soft_check(client):
    r = await client.get("/health")
    x_frame = r.headers.get("x-frame-options")
    x_content_type = r.headers.get("x-content-type-options")
    csp = r.headers.get("content-security-policy")

    assert x_frame in {"DENY", "SAMEORIGIN"}, (
        f"ROUTES-012 FAIL: X-Frame-Options assente/non valido ({x_frame!r})"
    )
    assert x_content_type == "nosniff", (
        f"ROUTES-012 FAIL: X-Content-Type-Options assente/non valido ({x_content_type!r})"
    )
    assert csp and "default-src" in csp, (
        "ROUTES-012 FAIL: Content-Security-Policy assente o incompleta"
    )


# =============================================================================
# ROUTES-013  Endpoint inesistente -> 404
# =============================================================================


async def test_ROUTES_013_endpoint_inesistente(client):
    r = await client.get("/questo-endpoint-non-esiste")
    assert r.status_code == 404, (
        f"ROUTES-013 FAIL: endpoint inesistente status {r.status_code}, atteso 404"
    )
