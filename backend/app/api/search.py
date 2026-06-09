from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from ..write_buffer.buffer import write_buffer
from ..write_buffer.metrics import write_metrics

router = APIRouter()

class SearchRequest(BaseModel):
    query: str

@router.post("/search")
async def record_search(request: SearchRequest):
    """
    Receives a search query, records it in the in-memory write buffer,
    and returns immediately to avoid blocking the client on DB I/O.
    """
    query = request.query.strip().lower()
    if not query:
        return {"message": "Empty query ignored"}
        
    write_buffer.increment(query)
    write_metrics.record_search()
    
    return {"message": "Searched"}

@router.get("/write/metrics")
async def get_write_metrics():
    """
    Returns the current state of the write buffer and batch writer.
    """
    snapshot = write_metrics.get_snapshot()
    
    return {
        "searches_received": snapshot.searches_received,
        "flushes_executed": snapshot.flushes_executed,
        "db_writes_executed": snapshot.db_writes_executed,
        "db_writes_avoided": snapshot.db_writes_avoided,
        "write_reduction_percent": round(snapshot.write_reduction_percent, 2),
        "buffer_current_size": write_buffer.get_size()
    }
