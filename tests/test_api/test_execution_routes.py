"""Unit tests for execution and invoke API routes."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.gateway import Gateway
from agent_gateway.persistence.domain import ExecutionRecord
from agent_gateway.persistence.null import NullExecutionRepository
from agent_gateway.queue.protocol import ExecutionQueue


def _write_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with one agent and persistence disabled."""
    (tmp_path / "gateway.yaml").write_text("persistence:\n  enabled: false\n")
    agents = tmp_path / "agents"
    agents.mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()

    agent_dir = agents / "test-agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text("# Test Agent\n\nYou help with testing.\n")
    return tmp_path


def _make_record(
    execution_id: str = "exec-1",
    agent_id: str = "test-agent",
    status: str = "completed",
    **overrides: object,
) -> ExecutionRecord:
    fields = dict(
        id=execution_id,
        agent_id=agent_id,
        status=status,
        message="hello",
    )
    fields.update(overrides)
    return ExecutionRecord(**fields)  # type: ignore[arg-type]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return _write_workspace(tmp_path)


# ---------------------------------------------------------------------------
# Execution GET / list
# ---------------------------------------------------------------------------


async def test_get_execution_found(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_repo = AsyncMock(spec=NullExecutionRepository)
        mock_repo.get.return_value = _make_record()
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.get("/v1/executions/exec-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["execution_id"] == "exec-1"
    assert body["agent_id"] == "test-agent"
    assert body["status"] == "completed"
    mock_repo.get.assert_called_once_with("exec-1")


async def test_get_execution_not_found(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    # NullExecutionRepository.get returns None by default — no mock needed
    async with (
        gw,
        AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac,
    ):
        resp = await ac.get("/v1/executions/nonexistent")

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "execution_not_found"
    assert "message" in body["error"]


async def test_list_executions_all(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_repo = AsyncMock(spec=NullExecutionRepository)
        mock_repo.list_all.return_value = [
            _make_record("exec-1"),
            _make_record("exec-2"),
        ]
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.get("/v1/executions")

    assert resp.status_code == 200
    assert len(resp.json()) == 2
    mock_repo.list_all.assert_called_once()


async def test_list_executions_by_agent(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_repo = AsyncMock(spec=NullExecutionRepository)
        mock_repo.list_by_agent.return_value = [_make_record()]
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.get("/v1/executions", params={"agent_id": "test-agent"})

    assert resp.status_code == 200
    assert len(resp.json()) == 1
    mock_repo.list_by_agent.assert_called_once_with("test-agent", limit=50)


async def test_list_executions_by_session(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_repo = AsyncMock(spec=NullExecutionRepository)
        mock_repo.list_by_session.return_value = [_make_record(session_id="sess-1")]
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.get("/v1/executions", params={"session_id": "sess-1"})

    assert resp.status_code == 200
    assert len(resp.json()) == 1
    mock_repo.list_by_session.assert_called_once_with("sess-1", limit=50)


async def test_list_executions_by_root(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_repo = AsyncMock(spec=NullExecutionRepository)
        mock_repo.list_by_root_execution.return_value = [
            _make_record(root_execution_id="root-1"),
        ]
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.get("/v1/executions", params={"root_execution_id": "root-1"})

    assert resp.status_code == 200
    assert len(resp.json()) == 1
    mock_repo.list_by_root_execution.assert_called_once_with("root-1")


# ---------------------------------------------------------------------------
# Workflow tree
# ---------------------------------------------------------------------------


async def test_workflow_tree_found(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_repo = AsyncMock(spec=NullExecutionRepository)
        root_record = _make_record("exec-1", root_execution_id=None)
        mock_repo.get.return_value = root_record
        mock_repo.list_by_root_execution.return_value = [
            _make_record("exec-1"),
            _make_record("exec-2", root_execution_id="exec-1"),
            _make_record("exec-3", root_execution_id="exec-1"),
        ]
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.get("/v1/executions/exec-1/workflow")

    assert resp.status_code == 200
    assert len(resp.json()) == 3
    mock_repo.get.assert_called_once_with("exec-1")


async def test_workflow_tree_not_found(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    # NullExecutionRepository returns None for get()
    async with (
        gw,
        AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac,
    ):
        resp = await ac.get("/v1/executions/nonexistent/workflow")

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "execution_not_found"
    assert "message" in body["error"]


# ---------------------------------------------------------------------------
# Cancel endpoint
# ---------------------------------------------------------------------------


async def test_cancel_in_memory_handle(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_handle = MagicMock()
        gw._execution_handles["exec-1"] = mock_handle

        mock_repo = AsyncMock(spec=NullExecutionRepository)
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.post("/v1/executions/exec-1/cancel")

    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    mock_handle.cancel.assert_called_once()
    mock_repo.update_status.assert_called_once()


async def test_cancel_via_queue(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_queue = cast("ExecutionQueue", AsyncMock())
        mock_queue.request_cancel.return_value = True  # type: ignore[union-attr]
        gw._queue = mock_queue

        mock_repo = AsyncMock(spec=NullExecutionRepository)
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.post("/v1/executions/exec-1/cancel")

    assert resp.status_code == 200
    assert resp.json()["status"] == "cancel_requested"


async def test_cancel_terminal_state(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_repo = AsyncMock(spec=NullExecutionRepository)
        mock_repo.get.return_value = _make_record(status="completed")
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.post("/v1/executions/exec-1/cancel")

    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "invalid_state"
    assert "message" in body["error"]


async def test_cancel_not_found(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    # NullExecutionRepository: no handle, NullQueue, repo returns None
    async with (
        gw,
        AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac,
    ):
        resp = await ac.post("/v1/executions/exec-1/cancel")

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "execution_not_found"
    assert "message" in body["error"]


# ---------------------------------------------------------------------------
# Async invoke
# ---------------------------------------------------------------------------


async def test_async_invoke_queued(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_queue = cast("ExecutionQueue", AsyncMock())
        gw._queue = mock_queue

        mock_repo = AsyncMock(spec=NullExecutionRepository)
        gw._execution_repo = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.post(
                "/v1/agents/test-agent/invoke",
                json={
                    "message": "hi",
                    "options": {"async_": True},
                },
            )

    assert resp.status_code == 202
    body = resp.json()
    assert "execution_id" in body
    assert "poll_url" in body


async def test_async_invoke_stream_rejected(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with gw:
        mock_queue = cast("ExecutionQueue", AsyncMock())
        gw._queue = mock_queue

        async with AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac:
            resp = await ac.post(
                "/v1/agents/test-agent/invoke",
                json={
                    "message": "hi",
                    "options": {"async_": True, "stream": True},
                },
            )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "streaming_not_supported"


async def test_invoke_agent_not_found(workspace: Path) -> None:
    gw = Gateway(workspace=str(workspace), auth=False)
    async with (
        gw,
        AsyncClient(
            transport=ASGITransport(app=gw),
            base_url="http://test",  # type: ignore[arg-type]
        ) as ac,
    ):
        resp = await ac.post(
            "/v1/agents/nonexistent/invoke",
            json={"message": "hi"},
        )

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "agent_not_found"
