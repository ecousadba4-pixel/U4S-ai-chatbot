from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.security import verify_api_key
from app.rag.qdrant_client import QdrantClient, get_qdrant_client
from app.rag.retriever import search_hits_with_payload

router = APIRouter(prefix="/rag", dependencies=[Depends(verify_api_key)])


@router.get("/search")
async def rag_search(
    q: str = Query(..., description="Поисковый запрос"),
    qdrant: QdrantClient = Depends(get_qdrant_client),
) -> dict:
    hits = await search_hits_with_payload(query=q, client=qdrant)
    return {"facts": hits.get("facts", []), "files": hits.get("files", [])}


__all__ = ["router"]
