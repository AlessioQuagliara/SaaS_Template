# =============================================================================
# backend/app/schemas/tenant.py
# =============================================================================

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

# -----------------------------------------------------------------------------
# SCHEMI TENANT ---------------------------------------------------------------
# -----------------------------------------------------------------------------

class TenantBase(BaseModel):
    slug: str
    nome: str

class TenantCreazione(TenantBase):
    pass

class TenantLettura(TenantBase):
    id: int
    attivo: bool
    creato_il: datetime

    model_config = {"from_attributes": True}