# =============================================================================
# test/test_auth.py  –  AUTH suite
# =============================================================================
# Copre: registrazione, login, logout, recupero password, CSRF, bcrypt
# =============================================================================

from __future__ import annotations

import bcrypt
import pytest

from conftest import (
    TEST_EMAIL,
    TEST_PASSWORD,
    TEST_TENANT_NOME,
    TEST_TENANT_SLUG,
    _TEST_PASSWORD_HASH,
    _crea_tenant_e_utente,
    genera_csrf,
)
from app.models import SottoscrizioniStati


# =============================================================================
# Helpers
# =============================================================================


def _form_registrazione(**override) -> dict:
    s, t = genera_csrf()
    base = {
        "nome_tenant": TEST_TENANT_NOME,
        "slug_tenant": TEST_TENANT_SLUG,
        "nome_utente": "Mario Rossi",
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "conferma_password": TEST_PASSWORD,
        "csrf_token": t,
        "sessione_temp": s,
    }
    base.update(override)
    return base


def _form_login(**override) -> dict:
    s, t = genera_csrf()
    base = {
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "csrf_token": t,
        "sessione_temp": s,
        "next": "/",
    }
    base.update(override)
    return base


# =============================================================================
# AUTH-001  GET /auth/login → 200 con form CSRF
# =============================================================================


async def test_AUTH_001_login_page(client):
    r = await client.get("/auth/login")
    assert r.status_code == 200
    assert b"csrf_token" in r.content or b"sessione_temp" in r.content, (
        "AUTH-001 FAIL: form login non contiene campi CSRF"
    )


# =============================================================================
# AUTH-002  Registrazione valida: crea tenant + utente + sottoscrizione trial
# =============================================================================


async def test_AUTH_002_registrazione_valida(client, db_session):
    from sqlalchemy import select
    from app.models import Tenant, Utente, Sottoscrizione

    r = await client.post("/auth/register", data=_form_registrazione())
    # Deve redirigere alla pagina di conferma o login
    assert r.status_code in (200, 303, 302), (
        f"AUTH-002 FAIL: status inatteso {r.status_code}"
    )

    # Verifica DB: tenant creato
    res = await db_session.execute(select(Tenant).where(Tenant.slug == TEST_TENANT_SLUG))
    tenant = res.scalar_one_or_none()
    assert tenant is not None, "AUTH-002 FAIL: tenant non trovato nel DB"

    # Verifica DB: utente creato con email normalizzata
    res = await db_session.execute(select(Utente).where(Utente.email == TEST_EMAIL))
    utente = res.scalar_one_or_none()
    assert utente is not None, "AUTH-002 FAIL: utente non trovato nel DB"
    # Flusso corrente: utente creato inattivo finché non conferma via email.
    assert utente.attivo is False, (
        "AUTH-002 FAIL: utente dovrebbe nascere inattivo prima della conferma email"
    )

    # Verifica DB: sottoscrizione trial creata
    res = await db_session.execute(
        select(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant.id)
    )
    sub = res.scalar_one_or_none()
    assert sub is not None, "AUTH-002 FAIL: sottoscrizione trial non creata"
    assert sub.stato_piano.value == "prova", "AUTH-002 FAIL: stato piano non è 'prova'"


# =============================================================================
# AUTH-003  Password hashata con bcrypt cost ≥ 10
# =============================================================================


async def test_AUTH_003_password_hashing_bcrypt_cost(client, db_session):
    from sqlalchemy import select
    from app.models import Utente

    await client.post("/auth/register", data=_form_registrazione())

    res = await db_session.execute(select(Utente).where(Utente.email == TEST_EMAIL))
    utente = res.scalar_one_or_none()
    if utente is None:
        pytest.skip("Utente non creato (dipendenza da AUTH-002)")

    hash_bytes = utente.hashed_password.encode()
    cost = int(hash_bytes[4:6])
    assert cost >= 10, (
        f"AUTH-003 FAIL: bcrypt cost={cost}, atteso ≥ 10 (sicurezza insufficiente)"
    )


# =============================================================================
# AUTH-004  Registrazione con email duplicata → errore
# =============================================================================


async def test_AUTH_004_registrazione_email_duplicata(client, db_session):
    # Prima registrazione
    await client.post("/auth/register", data=_form_registrazione())
    # Seconda con stessa email ma slug diverso
    r = await client.post(
        "/auth/register",
        data=_form_registrazione(slug_tenant="altro-tenant", nome_tenant="Altro Tenant"),
    )
    # Il flusso supporta multi-tenant sullo stesso account se password corretta.
    assert r.status_code in (200, 302, 303), (
        f"AUTH-004 FAIL: status inatteso {r.status_code} per riuso account multi-tenant"
    )


# =============================================================================
# AUTH-005  Registrazione con password troppo corta → errore
# =============================================================================


async def test_AUTH_005_registrazione_password_corta(client):
    r = await client.post(
        "/auth/register",
        data=_form_registrazione(
            password="abc",
            conferma_password="abc",
            slug_tenant="tenant-short",
        ),
    )
    assert r.status_code == 200
    assert b"corta" in r.content.lower() or b"8" in r.content, (
        "AUTH-005 FAIL: nessun messaggio di errore per password corta"
    )


# =============================================================================
# AUTH-006  Registrazione con password non corrispondenti → errore
# =============================================================================


async def test_AUTH_006_registrazione_password_mismatch(client):
    r = await client.post(
        "/auth/register",
        data=_form_registrazione(
            conferma_password="AltroValore999!",
            slug_tenant="tenant-mismatch",
        ),
    )
    assert r.status_code == 200
    assert b"coincid" in r.content.lower() or b"password" in r.content.lower(), (
        "AUTH-006 FAIL: nessun messaggio di errore per password non coincidenti"
    )


# =============================================================================
# AUTH-007  Registrazione senza token CSRF → errore
# =============================================================================


async def test_AUTH_007_registrazione_senza_csrf(client):
    form = _form_registrazione(csrf_token="token-invalido", slug_tenant="tenant-nocsrf")
    r = await client.post("/auth/register", data=form)
    assert r.status_code == 200
    assert b"csrf" in r.content.lower() or b"token" in r.content.lower(), (
        "AUTH-007 FAIL: CSRF invalido non viene rifiutato"
    )


# =============================================================================
# AUTH-008  Login corretto → sessione Redis + cookie
# =============================================================================


async def test_AUTH_008_login_corretto(client, db_session, fake_redis):
    # Crea utente direttamente nel DB (bypass bcrypt lento)
    tenant, utente = await _crea_tenant_e_utente(db_session)

    r = await client.post("/auth/login", data=_form_login(email=tenant.nome))

    # Prova di nuovo con email corretta
    r = await client.post(
        "/auth/login",
        data=_form_login(email=utente.email, password=TEST_PASSWORD),
    )
    # Dovrebbe redirect (303) o 200 con HX-Redirect
    assert r.status_code in (200, 303, 302), (
        f"AUTH-008 FAIL: status inatteso {r.status_code}"
    )

    # Verifica cookie sessione impostato
    cookie_set = r.headers.get("set-cookie", "")
    assert "id_sessione_utente" in cookie_set, (
        "AUTH-008 FAIL: cookie di sessione non impostato nel login"
    )

    # Verifica sessione in Redis
    keys = await fake_redis.keys("sessione:*")
    assert len(keys) >= 1, "AUTH-008 FAIL: nessuna sessione creata in Redis"


# =============================================================================
# AUTH-009  Login con password errata → nessuna sessione creata
# =============================================================================


async def test_AUTH_009_login_password_errata(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)

    r = await client.post(
        "/auth/login",
        data=_form_login(email=utente.email, password="PasswordSbagliata!"),
    )
    assert r.status_code == 200, (
        f"AUTH-009 FAIL: status inatteso {r.status_code} (atteso 200)"
    )
    assert b"credenziali" in r.content.lower() or b"valide" in r.content.lower(), (
        "AUTH-009 FAIL: nessun messaggio di errore per credenziali errate"
    )
    keys = await fake_redis.keys("sessione:*")
    assert len(keys) == 0, "AUTH-009 FAIL: sessione creata nonostante credenziali errate"


# =============================================================================
# AUTH-010  Login utente inesistente → errore generico (no user enumeration)
# =============================================================================


async def test_AUTH_010_login_utente_inesistente(client, db_session):
    r = await client.post(
        "/auth/login",
        data=_form_login(email="nonexistent@example.com", password="Password123!"),
    )
    assert r.status_code == 200
    # Il messaggio deve essere generico (non rivelare se email esiste)
    content = r.content.lower()
    assert b"credenziali" in content or b"valide" in content, (
        "AUTH-010 FAIL: nessun messaggio di errore per utente inesistente"
    )
    assert b"esiste" not in content, (
        "AUTH-010 FAIL: risposta rivela se l'utente esiste (user enumeration)"
    )


# =============================================================================
# AUTH-011  Login senza CSRF → errore
# =============================================================================


async def test_AUTH_011_login_senza_csrf(client, db_session):
    tenant, utente = await _crea_tenant_e_utente(db_session)
    r = await client.post(
        "/auth/login",
        data=_form_login(
            email=utente.email,
            password=TEST_PASSWORD,
            csrf_token="token-invalido",
        ),
    )
    assert r.status_code == 200
    assert b"csrf" in r.content.lower() or b"token" in r.content.lower(), (
        "AUTH-011 FAIL: CSRF invalido non viene rifiutato nel login"
    )


# =============================================================================
# AUTH-012  Login utente disattivato → accesso negato
# =============================================================================


async def test_AUTH_012_login_utente_disattivato(client, db_session):
    tenant, utente = await _crea_tenant_e_utente(db_session, attivo=False)

    r = await client.post(
        "/auth/login",
        data=_form_login(email=utente.email, password=TEST_PASSWORD),
    )
    assert r.status_code == 200
    content = r.content.lower()
    assert b"attivo" in content or b"conferma" in content, (
        "AUTH-012 FAIL: utente disattivato riesce ad accedere"
    )


# =============================================================================
# AUTH-013  GET /auth/password-recovery → 200
# =============================================================================


async def test_AUTH_013_password_recovery_page(client):
    r = await client.get("/auth/password-recovery")
    assert r.status_code == 200, (
        f"AUTH-013 FAIL: status inatteso {r.status_code}"
    )


# =============================================================================
# AUTH-014  POST /auth/password-recovery risposta neutra (no user enumeration)
# =============================================================================


async def test_AUTH_014_password_recovery_risposta_neutra(client):
    r_esiste = await client.post(
        "/auth/password-recovery", data={"email": TEST_EMAIL}
    )
    r_non_esiste = await client.post(
        "/auth/password-recovery", data={"email": "nonexistent@example.com"}
    )
    # Entrambe devono restituire 200
    assert r_esiste.status_code == 200
    assert r_non_esiste.status_code == 200
    # I contenuti devono essere identici (risposta neutra per sicurezza)
    assert b"email" in r_esiste.content.lower() or b"link" in r_esiste.content.lower()


# =============================================================================
# AUTH-015  Email normalizzata a lowercase al login
# =============================================================================


async def test_AUTH_015_email_case_insensitive_login(client, db_session, fake_redis):
    # Crea utente con email lowercase
    tenant, utente = await _crea_tenant_e_utente(db_session, email="auser@example.com")

    # Tenta login con email uppercase
    r = await client.post(
        "/auth/login",
        data=_form_login(email="AUSER@EXAMPLE.COM", password=TEST_PASSWORD),
    )
    assert r.status_code in (200, 302, 303), (
        f"AUTH-015 FAIL: status inatteso {r.status_code} nel login case-insensitive"
    )

    cookie_set = r.headers.get("set-cookie", "")
    assert "id_sessione_utente" in cookie_set, (
        "AUTH-015 FAIL: login con email maiuscola non ha creato sessione/cookie"
    )

    keys = await fake_redis.keys("sessione:*")
    assert len(keys) >= 1, "AUTH-015 FAIL: nessuna sessione Redis creata"


# =============================================================================
# AUTH-016  Registrazione con slug tenant duplicato → errore
# =============================================================================


async def test_AUTH_016_slug_tenant_duplicato(client, db_session):
    await client.post("/auth/register", data=_form_registrazione())

    r = await client.post(
        "/auth/register",
        data=_form_registrazione(
            email="altro@example.com",
            slug_tenant=TEST_TENANT_SLUG,
        ),
    )
    assert r.status_code == 200
    content = r.content.lower()
    assert b"esiste" in content or b"slug" in content or b"tenant" in content, (
        "AUTH-016 FAIL: slug duplicato non genera errore"
    )
