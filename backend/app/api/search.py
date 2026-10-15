from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..database.config import Settings, get_settings
from ..services.normalization import EmptyText, validate_text
from ..write_buffer.buffer import write_buffer
from ..write_buffer.metrics import write_metrics

router = APIRouter()

class SearchRequest(BaseModel):
    query: str

def _metrics_payload() -> dict:
    snapshot = write_metrics.get_snapshot()
    return {
        "searches_received": snapshot.searches_received,
        "flushes_executed": snapshot.flushes_executed,
        "db_writes_executed": snapshot.db_writes_executed,
        "db_writes_avoided": snapshot.db_writes_avoided,
        "write_reduction_percent": round(snapshot.write_reduction_percent, 2),
        "buffer_current_size": write_buffer.get_size(),
        "flush_failures": snapshot.flush_failures,
        "events_requeued": snapshot.events_requeued,
        "events_dropped": snapshot.events_dropped,
        "last_flush_duration_ms": round(snapshot.last_flush_duration_ms, 2),
        "max_flush_duration_ms": round(snapshot.max_flush_duration_ms, 2),
    }

@router.post("/search")
async def record_search(request: SearchRequest, settings: Settings = Depends(get_settings)):
    """
    Receives a search query, records it in the in-memory write buffer,
    and returns immediately to avoid blocking the client on DB I/O.

    The query is normalized exactly like read-path prefixes (otherwise a row written here could
    be unreachable from /suggest) and validated so it can always be persisted.
    """
    try:
        query = validate_text(request.query, settings.max_query_length, what="query")
    except EmptyText:
        return {"message": "Empty query ignored"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not write_buffer.increment(query):
        write_metrics.record_dropped()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="write buffer full",
                            headers={"Retry-After": "10"})
    write_metrics.record_search()

    return {"message": "Searched"}

@router.get("/write/metrics")
async def get_write_metrics():
    """
    Returns the current state of the write buffer and batch writer.
    """
    return _metrics_payload()
