from __future__ import annotations

from fastapi import FastAPI
from fastapi.requests import Request

from .api.suggestions import router as suggestions_router

app = FastAPI(title="TypeAheadX", version="1.0.0")
from fastapi.middleware.cors import CORSMiddleware

@app.on_event("startup")
def on_startup():
	pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(suggestions_router)


@app.get("/health")
def health():
	return {"status": "healthy", "service": "typeaheadx-api", "phase": "phase-1"}


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
	import time

	start = time.perf_counter()
	response = await call_next(request)
	total_ms = (time.perf_counter() - start) * 1000.0
	response.headers["X-Response-Time-ms"] = f"{total_ms:.2f}"
	return response
