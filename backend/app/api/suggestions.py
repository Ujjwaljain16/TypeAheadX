from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..database.config import Settings, get_settings
from ..database.session import get_session
from ..repositories.query_repository import QueryRepository
from ..schemas.response import SuggestionResponse
from ..services.suggestion_service import SuggestionService

router = APIRouter()


def get_repository() -> QueryRepository:
    return QueryRepository(get_session)


from ..cache.factory import CacheFactory

def build_service(settings: Settings) -> SuggestionService:
    return SuggestionService(
        get_repository(),
        cache=CacheFactory.get_cache(),
        max_prefix_length=settings.max_prefix_length,
        default_limit=settings.default_limit,
        cache_ttl_seconds=settings.cache_ttl_seconds,
    )


@lru_cache(maxsize=1)
def _shared_service() -> SuggestionService:
    # one instance for the process: the single-flight table must be shared between requests
    return build_service(get_settings())


def get_service() -> SuggestionService:
    return _shared_service()


@router.get("/suggest", response_model=SuggestionResponse, response_class=Response)
def suggest(
    q: str = Query(..., description="Prefix to search for"),
    service: SuggestionService = Depends(get_service),
) -> Response:
    try:
        normalized = service.validate_and_normalize(q)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # The service returns the already-serialised JSON body; returning a Response skips FastAPI's
    # second validation + serialisation pass (the schema is still advertised through response_model).
    return Response(content=service.suggest_json(normalized), media_type="application/json")
