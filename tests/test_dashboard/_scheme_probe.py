"""Helper: scheme-probe route factory. Deliberately NOT using
``from __future__ import annotations`` so FastAPI can resolve the ``Request``
type hint at registration time (see commit 2bd5868 for the history — mounted
OpenAPI breaks when the route's ``Request`` annotation is a string)."""

from fastapi import APIRouter, Request


def make_scheme_probe_router() -> APIRouter:
    router = APIRouter()

    @router.get("/_probe/scheme")
    async def probe(request: Request) -> dict[str, str]:
        return {"scheme": request.url.scheme}

    return router
