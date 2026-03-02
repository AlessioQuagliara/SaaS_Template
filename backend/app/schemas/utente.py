# =============================================================================
# backend/app/schemas/utente.py
# =============================================================================

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr

# -----------------------------------------------------------------------------
# SCHEMI UTENTE ---------------------------------------------------------------
# -----------------------------------------------------------------------------

class UtenteBase(BaseModel):
    nome: str
    cognome: str
    email: EmailStr

class UtenteCreazione(UtenteBase):
    password: str

class UtenteLettura(UtenteBase):
    id: int
    tenant_id: int
    creato_il: datetime

    model_config = {"from_attributes": True}