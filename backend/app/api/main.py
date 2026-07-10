"""Colosseum FastAPI application."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api.routers import catalog, comparison, documents, gold, packs, prompts, runs

REPO_ROOT = Path(__file__).resolve().parents[3]


class SPAStaticFiles(StaticFiles):
    """Serve index.html for client-side React routes."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
        else:
            if response.status_code != 404:
                return response
        return await super().get_response("index.html", scope)


def create_app() -> FastAPI:
    application = FastAPI(
        title="Colosseum API",
        version="2.0.0",
        description="Benchmark runs, datasets, prompt versions, model catalog, and comparisons.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8100",
            "http://127.0.0.1:8100",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        runs.router,
        documents.router,
        gold.router,
        prompts.router,
        catalog.router,
        packs.router,
        comparison.router,
    ):
        application.include_router(router, prefix="/api")

    @application.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    frontend = REPO_ROOT / "frontend" / "dist"
    if frontend.is_dir():
        application.mount("/", SPAStaticFiles(directory=frontend, html=True), name="frontend")
    return application


app = create_app()
