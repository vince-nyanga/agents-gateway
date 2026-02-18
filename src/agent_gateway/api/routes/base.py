"""Custom APIRoute subclass for agent gateway endpoints."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute


class GatewayAPIRoute(APIRoute):
    """Custom route class for /v1/ endpoints.

    - Auto-injects execution_id into request.state
    - Adds X-Execution-Id response header
    - Records request duration via X-Request-Duration-Ms header
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def custom_handler(request: Request) -> Response:
            execution_id = str(uuid.uuid4())
            request.state.execution_id = execution_id
            start = time.monotonic()

            response = await original_handler(request)

            duration_ms = int((time.monotonic() - start) * 1000)
            response.headers["X-Execution-Id"] = execution_id
            response.headers["X-Request-Duration-Ms"] = str(duration_ms)
            return response

        return custom_handler
