# backend/app/cli/inseminamento.py (o seed.py)
from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.sicurezza import hash_password
from app.models import Tenant, Utente, UtenteRuolo


app = typer.Typer(help="Comandi di seed/dati iniziali.")


async def _seed_tenant_and_admin(
    slug: str,
    nome_tenant: str,
    admin_email: str,
    admin_password: str,
) -> None:
    async with AsyncSessionLocal() as session:
        # 1) Tenant
        result = await session.execute(
            select(Tenant).where(Tenant.slug == slug)
        )
        tenant = result.scalar_one_or_none()

        if tenant is None:
            tenant = Tenant(slug=slug, nome=nome_tenant, attivo=True)
            session.add(tenant)
            await session.flush()
            typer.echo(f"[OK] Creato tenant '{slug}' (id={tenant.id})")
        else:
            typer.echo(f"[INFO] Tenant '{slug}' esiste già (id={tenant.id})")

        # 2) Admin
        result = await session.execute(
            select(Utente).where(Utente.email == admin_email)
        )
        admin = result.scalar_one_or_none()

        if admin is None:
            hashed = hash_password(admin_password)
            admin = Utente(
                tenant_id=tenant.id,
                nome="Admin",
                cognome="",
                email=admin_email,
                hashed_password=hashed,
                attivo=True,
                ruolo=UtenteRuolo.SUPERUTENTE,
            )
            session.add(admin)
            await session.commit()
            typer.secho(
                f"[OK] Creato admin '{admin_email}' per tenant '{slug}'",
                fg=typer.colors.GREEN,
            )
        else:
            typer.echo(
                f"[INFO] Utente admin '{admin_email}' esiste già (tenant_id={admin.tenant_id})"
            )


@app.command("tenant-admin")
def seed_tenant_and_admin(
    slug: Annotated[str, typer.Option(help="Slug tenant, es. 'demo'")] = "demo",
    nome_tenant: Annotated[
        str, typer.Option("--nome-tenant", help="Nome tenant, es. 'Tenant Demo'")
    ] = "Tenant Demo",
    admin_email: Annotated[
        str, typer.Option("--admin-email", help="Email admin")
    ] = "admin@demo.com",
    admin_password: Annotated[
        str, typer.Option("--admin-password", help="Password admin in chiaro")
    ] = "changeme",
) -> None:
    """
    Crea (se non esistono) un tenant e un utente admin associato.
    """
    asyncio.run(
        _seed_tenant_and_admin(slug, nome_tenant, admin_email, admin_password)
    )
