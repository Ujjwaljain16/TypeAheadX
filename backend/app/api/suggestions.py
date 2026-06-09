from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..database.config import Settings, get_settings
from ..database.session import get_session
from ..repositories.query_repository import QueryRepository
from ..schemas.response import SuggestionResponse
from ..services.suggestion_service import SuggestionService

router = APIRouter()


def get_repository() -> QueryRepository:
    return QueryRepository(get_session)


from ..cache.factory import CacheFactory

def get_service(settings: Settings = Depends(get_settings)) -> SuggestionService:
    return SuggestionService(
        get_repository(),
        cache=CacheFactory.get_cache(),
        max_prefix_length=settings.max_prefix_length,
        default_limit=settings.default_limit,
        cache_ttl_seconds=settings.cache_ttl_seconds,
    )


@router.get("/suggest", response_model=SuggestionResponse)
def suggest(
    q: str = Query(..., description="Prefix to search for"),
    service: SuggestionService = Depends(get_service),
) -> SuggestionResponse:
    try:
        normalized = service.validate_and_normalize(q)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return service.suggest(normalized)
