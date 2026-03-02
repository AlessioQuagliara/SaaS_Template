# =============================================================================
# app/routes/core/__init__.py
# =============================================================================

from fastapi import APIRouter

from .controlli import router as controlli_routes

router = APIRouter(prefix="/controlli", tags=["auth"])
router.include_router(controlli_routes)

__all__ = ["router"]