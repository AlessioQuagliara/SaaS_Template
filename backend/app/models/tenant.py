# =============================================================================
# backend/app/models/tenant.py
# =============================================================================

from __future__ import annotations

from typing import List

from sqlalchemy import String, Boolean, DateTime, func

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# -----------------------------------------------------------------------------
# CLASSE TENANT ---------------------------------------------------------------
# -----------------------------------------------------------------------------

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        )

    slug: Mapped[str] = mapped_column(
        String(64), 
        unique=True, 
        index=True,
        )

    nome: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        )

    attivo: Mapped[bool] = mapped_column(
        Boolean, 
        default=True, 
        nullable=False,
        )

    creato_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False,
        )

    # Relazione con tabella Utenti
    utenti: Mapped[List["Utente"]] = relationship( 
        back_populates="tenant",
        )