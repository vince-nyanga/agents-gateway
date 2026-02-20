"""Tests for memory protocol conformance."""

from __future__ import annotations

from agent_gateway.memory.backends.file import FileMemoryBackend, FileMemoryRepository
from agent_gateway.memory.null import NullMemoryBackend, NullMemoryRepository
from agent_gateway.memory.protocols import MemoryBackend, MemoryRepository


class TestMemoryRepositoryProtocol:
    def test_null_repo_conforms(self) -> None:
        repo = NullMemoryRepository()
        assert isinstance(repo, MemoryRepository)

    def test_file_repo_conforms(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        repo = FileMemoryRepository(tmp_path)
        assert isinstance(repo, MemoryRepository)

    def test_non_conformance(self) -> None:
        class _Incomplete:
            async def save(self) -> None:
                pass

        assert not isinstance(_Incomplete(), MemoryRepository)


class TestMemoryBackendProtocol:
    def test_null_backend_conforms(self) -> None:
        backend = NullMemoryBackend()
        assert isinstance(backend, MemoryBackend)

    def test_file_backend_conforms(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        backend = FileMemoryBackend(tmp_path)
        assert isinstance(backend, MemoryBackend)
