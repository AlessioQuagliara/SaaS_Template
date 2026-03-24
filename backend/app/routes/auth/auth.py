# =============================================================================
# backend/app/routes/auth/auth.py
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter

from .login_routes import router as login_router
from .password_routes import router as password_router
from .register_routes import router as register_router
from .two_factor_routes import router as two_factor_router

router = APIRouter()
router.include_router(login_router)
router.include_router(register_router)
router.include_router(password_router)
router.include_router(two_factor_router)

__all__ = ["router"]
