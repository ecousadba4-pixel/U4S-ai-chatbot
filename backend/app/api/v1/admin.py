from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.rag.qdrant_client import QdrantClient, get_qdrant_client

router = APIRouter(prefix="/admin")


@router.get("/health")
async def health(
    qdrant: QdrantClient = Depends(get_qdrant_client),
) -> dict[str, bool | str]:
    """Проверка здоровья сервиса с проверкой Qdrant."""
    settings = get_settings()
    
    qdrant_ok = False
    try:
        result = await qdrant.scroll(collection=settings.qdrant_collection, limit=1)
        qdrant_ok = isinstance(result, list)
    except Exception:
        qdrant_ok = False
    
    return {
        "ok": qdrant_ok,
        "qdrant": "✓" if qdrant_ok else "✗",
    }
