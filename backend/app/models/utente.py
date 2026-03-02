# =============================================================================
# backend/app/models/utente.py
# =============================================================================

from __future__ import annotations

import enum

from sqlalchemy import String, Boolean, Integer, DateTime, func, ForeignKey, Enum

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# -----------------------------------------------------------------------------
# PERMESSI UTENTE -------------------------------------------------------------
# -----------------------------------------------------------------------------

class UtenteRuolo(str, enum.Enum):
    UTENTE = "utente"
    MODERATORE = "moderatore"
    COLLABORATORE = "collaboratore"
    SUPERUTENTE = "superutente"

# -----------------------------------------------------------------------------
# CLASSE UTENTE ---------------------------------------------------------------
# -----------------------------------------------------------------------------

class Utente(Base):
    __tablename__ = "utenti"

    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        )
    
    tenant_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey(
            "tenants.id", 
            ondelete="CASCADE",
            ), 
        index=True,
    )

    nome: Mapped[str] = mapped_column(
        String(255),
    )

    cognome: Mapped[str] = mapped_column(
        String(255),
    )

    email: Mapped[str] = mapped_column(
        String(255), 
        unique=True, 
        index=True,
        )

    hashed_password: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        )

    attivo: Mapped[bool] = mapped_column(
        Boolean, 
        default=True, 
        nullable=False,
        )

    ruolo: Mapped[UtenteRuolo] = mapped_column(
        Enum(UtenteRuolo),
        default=UtenteRuolo.UTENTE,
        nullable = False,
    )

    creato_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False,
        )

    # Relazione con Tenant
    tenant: Mapped["Tenant"] = relationship(
        back_populates="utenti"
    )