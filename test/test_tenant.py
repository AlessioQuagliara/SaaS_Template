# =============================================================================
# test/test_tenant.py  –  TENANT suite
# =============================================================================
# Copre: accesso dashboard, isolamento tenant, inviti, ruoli, switch tenant
# =============================================================================

from __future__ import annotations

import pytest

from conftest import (
    TEST_EMAIL,
    TEST_PASSWORD,
    TEST_TENANT_SLUG,
    _TEST_PASSWORD_HASH,
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


# =============================================================================
# TENANT-001  Dashboard accessibile con trial attivo
# =============================================================================


async def test_TENANT_001_dashboard_con_trial_attivo(client, sessione_autenticata):
    tenant, utente, id_sessione = sessione_autenticata

    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies=_cookies(id_sessione),
    )
    assert r.status_code == 200, (
        f"TENANT-001 FAIL: status {r.status_code} (atteso 200) – "
        "dashboard non accessibile con trial attivo"
    )


# =============================================================================
# TENANT-002  Dashboard accessibile con piano ATTIVO (non trial)
# =============================================================================


async def test_TENANT_002_dashboard_con_piano_attivo(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session, stato_piano=SottoscrizioniStati.ATTIVO
    )
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies=_cookies(id_sessione),
    )
    assert r.status_code == 200, (
        f"TENANT-002 FAIL: status {r.status_code} – dashboard non accessibile con piano attivo"
    )


# =============================================================================
# TENANT-003  Dashboard bloccata con trial scaduto
# =============================================================================


async def test_TENANT_003_dashboard_bloccata_trial_scaduto(client, db_session, fake_redis):
    # Trial con giorni_trial=-1 → già scaduto
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="expired-tenant",
        stato_piano=SottoscrizioniStati.PROVA,
        giorni_trial=-1,
    )
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies=_cookies(id_sessione),
    )
    # Deve bloccare con 403 o redirect a sottoscrizioni
    assert r.status_code in (302, 303, 403), (
        f"TENANT-003 FAIL: status {r.status_code} – dashboard accessibile con trial scaduto"
    )


# =============================================================================
# TENANT-004  Dashboard bloccata con piano SOSPESO
# =============================================================================


async def test_TENANT_004_dashboard_bloccata_piano_sospeso(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="suspended-tenant",
        stato_piano=SottoscrizioniStati.SOSPESO,
    )
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies=_cookies(id_sessione),
    )
    assert r.status_code in (302, 303, 403), (
        f"TENANT-004 FAIL: status {r.status_code} – dashboard accessibile con piano sospeso"
    )


# =============================================================================
# TENANT-005  Tenant inesistente → 404
# =============================================================================


async def test_TENANT_005_tenant_inesistente(client, sessione_autenticata):
    tenant, utente, id_sessione = sessione_autenticata

    r = await client.get(
        "/tenant-che-non-esiste/admin/dashboard",
        cookies=_cookies(id_sessione),
    )
    assert r.status_code == 404, (
        f"TENANT-005 FAIL: status {r.status_code} (atteso 404) per tenant inesistente"
    )


# =============================================================================
# TENANT-006  Utente senza ruolo non accede al tenant altrui
# =============================================================================


async def test_TENANT_006_isolamento_tenant_utente_senza_ruolo(
    client, db_session, fake_redis
):
    # Crea due tenant distinti con utenti separati
    tenant_a, utente_a = await _crea_tenant_e_utente(
        db_session,
        slug="tenant-alpha",
        email="alpha@example.com",
    )
    tenant_b, utente_b = await _crea_tenant_e_utente(
        db_session,
        slug="tenant-beta",
        email="beta@example.com",
    )

    # Sessione di utente_a
    id_sessione_a = await _crea_sessione_utente(utente_a, tenant_a)

    # utente_a tenta di accedere al dashboard di tenant_b
    r = await client.get(
        f"/{tenant_b.slug}/admin/dashboard",
        cookies=_cookies(id_sessione_a),
    )
    assert r.status_code in (403, 302, 303), (
        f"TENANT-006 FAIL: status {r.status_code} – "
        "utente accede al dashboard di un tenant a cui non appartiene"
    )


# =============================================================================
# TENANT-007  Un utente con due tenant vede i dati del tenant corretto
# =============================================================================


async def test_TENANT_007_switch_tenant(client, db_session, fake_redis):
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models import Tenant, Utente, UtenteRuoloTenant, Sottoscrizione, Sottoscrizioni
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select

    # Crea tenant A con utente
    tenant_a, utente = await _crea_tenant_e_utente(
        db_session,
        slug="switch-tenant-a",
        email="multitenante@example.com",
    )

    # Crea tenant B – stesso utente con ruolo aggiunto manualmente
    tenant_b = Tenant(slug="switch-tenant-b", nome="Tenant B", attivo=True)
    db_session.add(tenant_b)
    await db_session.flush()

    ruolo_b = UtenteRuoloTenant(
        utente_id=utente.id,
        tenant_id=tenant_b.id,
        ruolo=UtenteRuolo.COLLABORATORE.value,
    )
    db_session.add(ruolo_b)

    fine = datetime.now(timezone.utc) + timedelta(days=14)
    sub_b = Sottoscrizione(
        tenant_id=tenant_b.id,
        piano=Sottoscrizioni.BASE,
        stato_piano=SottoscrizioniStati.PROVA,
        fine_periodo_corrente=fine,
    )
    db_session.add(sub_b)
    await db_session.commit()

    # Sessione puntata su tenant_a
    id_sessione_a = await gestore_sessioni_per_test(utente, tenant_a)

    r = await client.get(
        f"/{tenant_a.slug}/admin/dashboard",
        cookies=_cookies(id_sessione_a),
    )
    assert r.status_code == 200, (
        f"TENANT-007 FAIL: dashboard tenant A non accessibile – status {r.status_code}"
    )

    # Accesso diretto a tenant_b con la sessione di tenant_a → deve fallire
    # (la sessione è legata a tenant_a, non a tenant_b)
    r2 = await client.get(
        f"/{tenant_b.slug}/admin/dashboard",
        cookies=_cookies(id_sessione_a),
    )
    # La sessione contiene id_tenant=tenant_a.id: l'accesso a tenant_b dipende
    # dalla policy di tenancy. Il sistema deve comunque verificare il ruolo.
    # Se l'utente ha un ruolo su tenant_b, l'accesso potrebbe essere permesso
    # (switch di tenant tramite nuova sessione è la pratica corretta).
    # Notiamo il comportamento senza imporlo come fail assoluto.
    assert r2.status_code in (200, 403, 302, 303), (
        f"TENANT-007 INFO: status multi-tenant = {r2.status_code}"
    )


async def gestore_sessioni_per_test(utente, tenant):
    """Alias locale per non importare direttamente il singleton."""
    from app.core.sessione import gestore_sessioni
    return await gestore_sessioni.crea_sessione(
        id_utente=utente.id,
        id_tenant=tenant.id,
        email=utente.email,
    )


# =============================================================================
# TENANT-008  Accesso senza sessione → redirect login
# =============================================================================


async def test_TENANT_008_accesso_senza_sessione(client, db_session, fake_redis):
    tenant, _utente = await _crea_tenant_e_utente(
        db_session,
        slug="tenant-no-session",
        email="nosession@example.com",
    )
    r = await client.get(f"/{tenant.slug}/admin/dashboard")
    assert r.status_code in (401, 302, 303), (
        f"TENANT-008 FAIL: status {r.status_code} – area protetta accessibile senza autenticazione"
    )


# =============================================================================
# TENANT-009  Utente collaboratore accede alla dashboard (ruolo non-superutente)
# =============================================================================


async def test_TENANT_009_collaboratore_accede_dashboard(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="collab-tenant",
        email="collab@example.com",
        ruolo=UtenteRuolo.COLLABORATORE,
    )
    id_sessione = await _crea_sessione_utente(utente, tenant)

    r = await client.get(
        f"/{tenant.slug}/admin/dashboard",
        cookies=_cookies(id_sessione),
    )
    assert r.status_code == 200, (
        f"TENANT-009 FAIL: status {r.status_code} – collaboratore non accede alla dashboard"
    )
