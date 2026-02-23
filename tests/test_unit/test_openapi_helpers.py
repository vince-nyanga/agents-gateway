"""Unit tests for OpenAPI documentation helpers."""

from __future__ import annotations

from agent_gateway.api.models import ErrorResponse
from agent_gateway.api.openapi import build_responses


def test_build_responses_empty() -> None:
    """Empty call returns empty dict."""
    assert build_responses() == {}


def test_build_responses_auth() -> None:
    """auth=True adds 401 and 403."""
    result = build_responses(auth=True)
    assert 401 in result
    assert 403 in result
    assert result[401]["model"] is ErrorResponse
    assert result[403]["model"] is ErrorResponse


def test_build_responses_not_found() -> None:
    """not_found=True adds 404."""
    result = build_responses(not_found=True)
    assert 404 in result
    assert result[404]["model"] is ErrorResponse


def test_build_responses_rate_limit() -> None:
    """rate_limit=True adds 429."""
    result = build_responses(rate_limit=True)
    assert 429 in result
    assert result[429]["model"] is ErrorResponse


def test_build_responses_combined() -> None:
    """Multiple flags combine correctly."""
    result = build_responses(auth=True, not_found=True, rate_limit=True)
    assert set(result.keys()) == {401, 403, 404, 429}


def test_build_responses_never_includes_422() -> None:
    """422 is never included (FastAPI auto-generates it)."""
    result = build_responses(auth=True, not_found=True, rate_limit=True)
    assert 422 not in result
