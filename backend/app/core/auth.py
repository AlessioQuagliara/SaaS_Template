# =============================================================================
# backend/app/core/auth.py
# =============================================================================

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

from app.core.tenancy import prendi_tenant_corrente

from app.models import Utente, Tenant

# Variabile di sessione
SESSION_COOKIE_NAME = "id_sessione_utente"

# Prendiamo utente corrente e se la sessione non corrisponde manda messeggi HTTP di errore
async def prendi_utente_corrente(
    id_sessione_utente: int | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    tenant: Tenant = Depends(prendi_tenant_corrente),
    db: AsyncSession = Depends(get_db),
) -> Utente:
    if id_sessione_utente is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non autenticato",
        )

    result = await db.execute(
        select(Utente).where(
            Utente.id == id_sessione_utente,
            Utente.tenant_id == tenant.id,
            Utente.attivo.is_(True),
        )
    )
    utente = result.scalar_one_or_none()

    if utente is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utente non valido per questo tenant",
        )

    return utente
