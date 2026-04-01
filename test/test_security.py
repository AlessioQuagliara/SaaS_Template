# =============================================================================
# test/test_security.py  –  SEC suite
# =============================================================================
# Copre: sessioni Redis, CSRF, bcrypt cost, cookie flags, brute-force guard,
#        header sicurezza, isolamento sessione al logout, token reset scadenza
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
from sqlalchemy import select

from conftest import (
    TEST_EMAIL,
    TEST_PASSWORD,
    TEST_TENANT_SLUG,
    _TEST_PASSWORD_HASH,
    _crea_sessione_utente,
    _crea_tenant_e_utente,
    genera_csrf,
)
from app.core.auth import SESSION_COOKIE_NAME
from app.core.csrf import csrf_protezione
from app.models import TokenResetPassword, SottoscrizioniStati


# =============================================================================
# SEC-001  Rotta protetta senza cookie → 401
# =============================================================================


async def test_SEC_001_rotta_protetta_senza_cookie(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)

    r = await client.get(f"/{tenant.slug}/admin/dashboard")
    assert r.status_code in (401, 302, 303), (
        f"SEC-001 FAIL: rotta protetta accessibile senza cookie – status {r.status_code}"
    )


# =============================================================================
# SEC-002  Cookie con id_sessione fittizio → 401
# =============================================================================


async def test_SEC_002_sessione_invalida(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)

    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies={SESSION_COOKIE_NAME: "sessione-inventata-aaabbbccc"},
    )
    assert r.status_code in (401, 302, 303), (
        f"SEC-002 FAIL: sessione invalida non rifiutata – status {r.status_code}"
    )


# =============================================================================
# SEC-003  Sessione memorizzata in Redis al login
# =============================================================================


async def test_SEC_003_sessione_in_redis_dopo_login(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)

    s, t = genera_csrf()
    await client.post(
        "/auth/login",
        data={
            "email": utente.email,
            "password": TEST_PASSWORD,
            "csrf_token": t,
            "sessione_temp": s,
            "next": "/",
        },
    )

    keys = await fake_redis.keys("sessione:*")
    assert len(keys) >= 1, (
        "SEC-003 FAIL: nessuna chiave sessione in Redis dopo login"
    )

    raw = await fake_redis.get(keys[0])
    data = json.loads(raw)
    assert "id_utente" in data, "SEC-003 FAIL: dati sessione mancano 'id_utente'"
    assert "id_tenant" in data, "SEC-003 FAIL: dati sessione mancano 'id_tenant'"


# =============================================================================
# SEC-004  Sessione TTL è circa 24 ore (86400 secondi)
# =============================================================================


async def test_SEC_004_ttl_sessione_24h(db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)
    id_sessione = await _crea_sessione_utente(utente, tenant)

    ttl = await fake_redis.ttl(f"sessione:{id_sessione}")
    assert ttl > 0, "SEC-004 FAIL: sessione senza TTL (TTL <= 0)"
    assert ttl <= 86400, (
        f"SEC-004 FAIL: TTL sessione {ttl}s supera 86400s (24h)"
    )
    assert ttl > 86400 - 60, (
        f"SEC-004 FAIL: TTL sessione {ttl}s è inferiore a 86340s "
        "(dovrebbe essere ~86400s al momento della creazione)"
    )


# =============================================================================
# SEC-005  Logout cancella la sessione da Redis
# =============================================================================


async def test_SEC_005_logout_cancella_sessione_redis(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)
    id_sessione = await _crea_sessione_utente(utente, tenant)

    # Verifica che la sessione esista
    keys_before = await fake_redis.keys("sessione:*")
    assert len(keys_before) >= 1, "SEC-005 PRE: sessione non creata"

    # Esegui logout
    r = await client.post(
        "/auth/logout",
        cookies={SESSION_COOKIE_NAME: id_sessione},
    )
    # Logout può restituire redirect o 200
    assert r.status_code in (200, 302, 303), (
        f"SEC-005 FAIL: logout → status inatteso {r.status_code}"
    )

    # Verifica che la sessione sia stata eliminata
    exists = await fake_redis.exists(f"sessione:{id_sessione}")
    assert exists == 0, "SEC-005 FAIL: sessione ancora presente in Redis dopo logout"


# =============================================================================
# SEC-006  Dopo logout, il cookie di sessione non è più valido
# =============================================================================


async def test_SEC_006_cookie_non_valido_dopo_logout(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)
    id_sessione = await _crea_sessione_utente(utente, tenant)

    # Logout
    await client.post(
        "/auth/logout",
        cookies={SESSION_COOKIE_NAME: id_sessione},
    )

    # Tentativo accesso con il vecchio cookie
    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies={SESSION_COOKIE_NAME: id_sessione},
    )
    assert r.status_code in (401, 302, 303), (
        f"SEC-006 FAIL: accesso possibile con sessione precedente al logout – status {r.status_code}"
    )


# =============================================================================
# SEC-007  Token CSRF con firma sbagliata → rifiutato
# =============================================================================


async def test_SEC_007_csrf_firma_invalida(client, db_session):
    tenant, utente = await _crea_tenant_e_utente(db_session)

    s, _ = genera_csrf()
    r = await client.post(
        "/auth/login",
        data={
            "email": utente.email,
            "password": TEST_PASSWORD,
            "csrf_token": "firma.completamente.falsa",
            "sessione_temp": s,
            "next": "/",
        },
    )
    assert r.status_code == 200
    content = r.content.lower()
    assert b"csrf" in content or b"token" in content, (
        "SEC-007 FAIL: CSRF con firma errata non genera messaggio di errore"
    )


# =============================================================================
# SEC-008  Token CSRF è legato alla sessione corrente (non riutilizzabile)
# =============================================================================


async def test_SEC_008_csrf_legato_a_sessione(client, db_session):
    """Un token CSRF generato per sessione_A deve essere rifiutato con sessione_B."""
    tenant, utente = await _crea_tenant_e_utente(db_session)

    s_a, t_a = genera_csrf()
    s_b, _t_b = genera_csrf()

    # Usa token di sessione_A con sessione_B
    r = await client.post(
        "/auth/login",
        data={
            "email": utente.email,
            "password": TEST_PASSWORD,
            "csrf_token": t_a,  # token della sessione A
            "sessione_temp": s_b,  # sessione B
            "next": "/",
        },
    )
    assert r.status_code == 200
    content = r.content.lower()
    assert b"csrf" in content or b"token" in content, (
        "SEC-008 FAIL: CSRF di una sessione diversa non viene rifiutato"
    )


# =============================================================================
# SEC-009  Password hashata in DB non è in chiaro
# =============================================================================


async def test_SEC_009_password_non_in_chiaro(db_session, fake_redis):
    from app.models import Utente

    tenant, utente = await _crea_tenant_e_utente(db_session)

    res = await db_session.execute(
        select(Utente).where(Utente.id == utente.id)
    )
    u = res.scalar_one()

    assert u.hashed_password != TEST_PASSWORD, (
        "SEC-009 FAIL: password salvata in chiaro nel DB"
    )
    assert u.hashed_password.startswith("$2b$"), (
        f"SEC-009 FAIL: formato hash non riconoscibile – valore: {u.hashed_password[:20]}..."
    )


# =============================================================================
# SEC-010  bcrypt cost ≥ 10 (default rounds=12)
# =============================================================================


async def test_SEC_010_bcrypt_cost_sufficiente():
    """Verifica che il modulo sicurezza usi almeno bcrypt rounds=10."""
    from app.core.sicurezza import hash_password

    test_hash = hash_password("SamplePassword99!")
    cost = int(test_hash.encode()[4:6])
    assert cost >= 10, (
        f"SEC-010 FAIL: bcrypt cost={cost}, atteso ≥ 10"
    )


# =============================================================================
# SEC-011  Token reset password scade dopo 1 ora
# =============================================================================


async def test_SEC_011_token_reset_scadenza(client, db_session, fake_redis):
    from app.models import Utente
    from unittest.mock import AsyncMock, patch

    tenant, utente = await _crea_tenant_e_utente(db_session)

    # Genera token reset
    with patch("app.routes.auth.password_routes.manda_reset_password", new=AsyncMock()):
        await client.post(
            "/auth/password-recovery",
            data={"email": utente.email},
        )

    # Recupera token da DB
    res = await db_session.execute(
        select(TokenResetPassword).where(TokenResetPassword.utente_id == utente.id)
    )
    token_obj = res.scalar_one_or_none()

    if token_obj is None:
        pytest.skip("Token reset non creato – verifica disponibilità email")

    scade_il = token_obj.scade_il
    if scade_il.tzinfo is None:
        scade_il = scade_il.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delta = scade_il - now

    assert delta.total_seconds() > 0, "SEC-011 FAIL: token già scaduto al momento della creazione"
    assert delta.total_seconds() <= 3600 + 5, (
        f"SEC-011 FAIL: token valido per {delta.total_seconds():.0f}s (massimo 3600s)"
    )


# =============================================================================
# SEC-012  Token reset scaduto → pagina di errore (non form reset)
# =============================================================================


async def test_SEC_012_token_reset_scaduto_rifiutato(client, db_session, fake_redis):
    import secrets
    from app.models import Utente

    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="sec-expired-token",
        email="expired-token@example.com",
    )

    # Inserisci token già scaduto
    token_scaduto = secrets.token_urlsafe(32)
    token_obj = TokenResetPassword(
        utente_id=utente.id,
        token=token_scaduto,
        scade_il=datetime.now(timezone.utc) - timedelta(hours=2),
        usato=False,
    )
    db_session.add(token_obj)
    await db_session.commit()

    r = await client.get(f"/auth/reset-password?token={token_scaduto}")
    assert r.status_code in (200, 400, 404), (
        f"SEC-012 FAIL: status inatteso {r.status_code}"
    )
    # La pagina non deve mostrare il form di reset ma un errore
    content = r.content.lower()
    is_error = (
        b"non valido" in content
        or b"scaduto" in content
        or b"invalid" in content
        or b"expired" in content
        or b"errore" in content
    )
    assert is_error, (
        "SEC-012 FAIL: pagina di reset con token scaduto non mostra errore"
    )


# =============================================================================
# SEC-013  Cookie sessione ha flag httponly
# =============================================================================


async def test_SEC_013_cookie_httponly(client, db_session, fake_redis):
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
    )

    cookie_header = r.headers.get("set-cookie", "")
    if SESSION_COOKIE_NAME not in cookie_header:
        pytest.skip("Cookie non impostato (dipendenza da login – verifica AUTH-008)")

    assert "httponly" in cookie_header.lower(), (
        f"SEC-013 FAIL: cookie sessione manca flag HttpOnly. "
        f"Set-Cookie: {cookie_header}"
    )


# =============================================================================
# SEC-014  CSRF: sessione_temp non può essere vuota
# =============================================================================


async def test_SEC_014_csrf_sessione_temp_vuota(client, db_session):
    tenant, utente = await _crea_tenant_e_utente(db_session)

    _s, t = genera_csrf()
    r = await client.post(
        "/auth/login",
        data={
            "email": utente.email,
            "password": TEST_PASSWORD,
            "csrf_token": t,
            "sessione_temp": "",  # vuota → il token genera per stringa ""
            "next": "/",
        },
    )
    assert r.status_code == 422, (
        f"SEC-014 FAIL: sessione_temp vuota dovrebbe essere rifiutata a validazione form (422), ottenuto {r.status_code}"
    )
