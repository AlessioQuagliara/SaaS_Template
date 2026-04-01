# =============================================================================
# test/conftest.py  –  Fixtures condivise per l'intera suite pytest
# =============================================================================
#
# Architettura di test:
#   - DB: SQLite in-memory via aiosqlite (nessun PostgreSQL richiesto)
#   - Redis: fakeredis (nessun server Redis richiesto)
#   - Email: monkeypatched (nessuna email reale inviata)
#   - Stripe: mocked via unittest.mock
#   - CSRF: generato con la stessa logica dell'applicazione
# =============================================================================

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import bcrypt
import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Forza cwd al backend così StaticFiles("app/static") risolve correttamente.
_TEST_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _TEST_DIR.parent / "backend"
os.chdir(_BACKEND_DIR)

# ---- path implicito da pytest.ini (pythonpath = ../backend) ----------------
from app.core.auth import SESSION_COOKIE_NAME
from app.core.database import Base, get_db
from app.core.sessione import gestore_sessioni
from app.main import create_app
from app.models import (
    Sottoscrizione,
    Sottoscrizioni,
    SottoscrizioniStati,
    Tenant,
    Utente,
    UtenteRuolo,
    UtenteRuoloTenant,
)
from app.routes.auth.helpers import nuovo_csrf_form

# =============================================================================
# COSTANTI DI TEST
# =============================================================================

TEST_EMAIL = "mario.rossi@example.com"
TEST_PASSWORD = "TestPassword123!"
TEST_TENANT_SLUG = "test-tenant"
TEST_TENANT_NOME = "Test Tenant Srl"

# Hash bcrypt con rounds=4 (veloce per i test) del TEST_PASSWORD
_TEST_PASSWORD_HASH: str = bcrypt.hashpw(
    TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)
).decode()


# =============================================================================
# ENGINE / SESSION SQLite in-memory
# =============================================================================

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def test_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Session diretta al DB di test – per verifiche lato DB nei test."""
    factory = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with factory() as session:
        yield session


# =============================================================================
# FAKE REDIS
# =============================================================================


@pytest_asyncio.fixture()
async def fake_redis():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    gestore_sessioni.redis = redis
    yield redis
    await redis.aclose()
    gestore_sessioni.redis = None


# =============================================================================
# HTTP TEST CLIENT
# =============================================================================


@pytest_asyncio.fixture()
async def client(test_engine, fake_redis):
    """AsyncClient httpx con DB e Redis sostituiti – nessuna I/O reale."""
    app = create_app()

    factory = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, class_=AsyncSession
    )

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _override_get_db

    # Blocca invio email reali in tutti i moduli che li importano
    with (
        patch("app.routes.auth.register_routes.manda_conferma_account", new=AsyncMock()),
        patch("app.routes.auth.password_routes.manda_reset_password", new=AsyncMock()),
        patch("app.routes.admin.users.manda_invito_utente", new=AsyncMock()),
        patch("app.routes.stripe.manda_notifica_sottoscrizione", return_value=None),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as ac:
            yield ac


# =============================================================================
# HELPERS DB
# =============================================================================


async def _crea_tenant_e_utente(
    session: AsyncSession,
    *,
    email: str = TEST_EMAIL,
    password_hash: str = _TEST_PASSWORD_HASH,
    ruolo: UtenteRuolo = UtenteRuolo.SUPERUTENTE,
    slug: str = TEST_TENANT_SLUG,
    nome_tenant: str = TEST_TENANT_NOME,
    stato_piano: SottoscrizioniStati = SottoscrizioniStati.PROVA,
    giorni_trial: int = 14,
    attivo: bool = True,
) -> tuple[Tenant, Utente]:
    tenant = Tenant(slug=slug, nome=nome_tenant, attivo=True)
    session.add(tenant)
    await session.flush()

    utente = Utente(
        email=email,
        hashed_password=password_hash,
        nome="Mario Rossi",
        attivo=attivo,
        tenant_id=tenant.id,
    )
    session.add(utente)
    await session.flush()

    ruolo_tenant = UtenteRuoloTenant(
        utente_id=utente.id,
        tenant_id=tenant.id,
        ruolo=ruolo.value,
    )
    session.add(ruolo_tenant)

    fine_trial = datetime.now(timezone.utc) + timedelta(days=giorni_trial)
    sottoscrizione = Sottoscrizione(
        tenant_id=tenant.id,
        piano=Sottoscrizioni.BASE,
        stato_piano=stato_piano,
        fine_periodo_corrente=(
            fine_trial if stato_piano == SottoscrizioniStati.PROVA else fine_trial
        ),
    )
    session.add(sottoscrizione)
    await session.commit()
    await session.refresh(tenant)
    await session.refresh(utente)
    return tenant, utente


@pytest_asyncio.fixture()
async def utente_e_tenant(db_session: AsyncSession):
    """Tenant + Superutente con trial attivo."""
    return await _crea_tenant_e_utente(db_session)


# =============================================================================
# HELPER: crea una sessione Redis e restituisce il cookie di sessione
# =============================================================================


async def _crea_sessione_utente(utente: Utente, tenant: Tenant) -> str:
    """Crea sessione in fake Redis e restituisce l'id di sessione."""
    return await gestore_sessioni.crea_sessione(
        id_utente=utente.id,
        id_tenant=tenant.id,
        email=utente.email,
    )


@pytest_asyncio.fixture()
async def sessione_autenticata(utente_e_tenant, fake_redis):
    """Restituisce (tenant, utente, cookie) già autenticati."""
    tenant, utente = utente_e_tenant
    id_sessione = await _crea_sessione_utente(utente, tenant)
    return tenant, utente, id_sessione


# =============================================================================
# HELPER CSRF pubblico (usabile nei test direttamente)
# =============================================================================


def genera_csrf() -> tuple[str, str]:
    """Genera una coppia (sessione_temp, csrf_token) valida."""
    return nuovo_csrf_form()
