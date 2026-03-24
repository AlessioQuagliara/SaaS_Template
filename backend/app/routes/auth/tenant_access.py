# =============================================================================
# backend/app/routes/auth/tenant_access.py
# =============================================================================

from __future__ import annotations

from sqlalchemy import and_, select

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload

from app.core.billing import applica_policy_disattivazione_tenant
from app.models import Tenant, UtenteRuoloTenant


async def carica_tenant_accessibili_utente(
    db: AsyncSession,
    id_utente: int,
) -> list[Tenant]:
    risultato_tenant = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.sottoscrizione))
        .join(
            UtenteRuoloTenant,
            and_(
                UtenteRuoloTenant.tenant_id == Tenant.id,
                UtenteRuoloTenant.utente_id == id_utente,
            ),
        )
        .where(Tenant.attivo.is_(True))
        .order_by(Tenant.nome.asc(), Tenant.id.asc())
    )
    tenant_risultati: list[Tenant] = []
    for tenant_item in risultato_tenant.scalars().all():
        tenant_eliminato = await applica_policy_disattivazione_tenant(
            db,
            tenant_obj=tenant_item,
        )
        if tenant_eliminato:
            continue
        # Include anche tenant sospesi/scaduti: l'utente deve poter accedere
        # all'area sottoscrizioni per riattivare il piano.
        tenant_risultati.append(tenant_item)
    return tenant_risultati
