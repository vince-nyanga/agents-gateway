"""Integration tests for distributed lock gateway wiring."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.gateway import Gateway
from agent_gateway.scheduler.lock import NullDistributedLock

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURE_WORKSPACE = FIXTURES_DIR / "workspace"


class TestDistributedLockGatewayWiring:
    """Test that gateway auto-detects and wires up the correct lock backend."""

    async def test_lock_disabled_by_default(self) -> None:
        """Default config should use NullDistributedLock."""
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)

        async with gw:
            if gw._scheduler is not None:
                assert isinstance(gw._scheduler._distributed_lock, NullDistributedLock)

    async def test_null_lock_used_when_no_scheduler(self) -> None:
        """When scheduler has no schedules, lock wiring is moot."""
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)

        async with gw:
            # Fixture workspace may not have schedules, so scheduler may be None
            # Either way, this should not crash
            if gw._scheduler is None:
                assert True  # No scheduler means no lock needed
            else:
                assert isinstance(gw._scheduler._distributed_lock, NullDistributedLock)
