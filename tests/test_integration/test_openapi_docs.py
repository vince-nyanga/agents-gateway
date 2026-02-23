"""Integration tests for OpenAPI schema documentation."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.gateway import Gateway

EXPECTED_TAG_NAMES = [
    "Health",
    "Agents",
    "Chat",
    "Sessions",
    "Conversations",
    "Executions",
    "Schedules",
    "Tools",
    "Skills",
    "User Config",
    "Admin",
]


def _get_schema(gw: Gateway) -> dict:
    """Get OpenAPI schema without starting the gateway."""
    return gw.openapi()


async def test_openapi_schema_includes_all_tags(tmp_path: Path) -> None:
    """All expected tag groups appear in the OpenAPI schema."""
    agent_dir = tmp_path / "workspace" / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text("---\ndescription: test\n---\nYou are a test agent.")

    gw = Gateway(workspace=str(tmp_path / "workspace"), auth=False)
    schema = _get_schema(gw)

    tag_names = [t["name"] for t in schema["tags"]]
    for expected in EXPECTED_TAG_NAMES:
        assert expected in tag_names, f"Missing tag: {expected}"


async def test_invoke_route_has_openapi_metadata(tmp_path: Path) -> None:
    """The invoke route has summary, tags, and error response codes."""
    agent_dir = tmp_path / "workspace" / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text("---\ndescription: test\n---\nYou are a test agent.")

    gw = Gateway(workspace=str(tmp_path / "workspace"), auth=False)
    schema = _get_schema(gw)

    invoke_path = schema["paths"]["/v1/agents/{agent_id}/invoke"]["post"]
    assert "summary" in invoke_path
    assert "Agents" in invoke_path["tags"]
    # Check error response codes are documented
    assert "401" in invoke_path["responses"]
    assert "404" in invoke_path["responses"]


async def test_health_route_has_health_tag(tmp_path: Path) -> None:
    """GET /v1/health has the Health tag."""
    agent_dir = tmp_path / "workspace" / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text("---\ndescription: test\n---\nYou are a test agent.")

    gw = Gateway(workspace=str(tmp_path / "workspace"), auth=False)
    schema = _get_schema(gw)

    health_path = schema["paths"]["/v1/health"]["get"]
    assert "Health" in health_path["tags"]


async def test_caller_tags_are_appended(tmp_path: Path) -> None:
    """Caller-supplied openapi_tags are appended after gateway defaults."""
    agent_dir = tmp_path / "workspace" / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text("---\ndescription: test\n---\nYou are a test agent.")

    custom_tags = [{"name": "Custom", "description": "A custom tag."}]
    gw = Gateway(
        workspace=str(tmp_path / "workspace"),
        auth=False,
        openapi_tags=custom_tags,
    )
    schema = _get_schema(gw)
    tag_names = [t["name"] for t in schema["tags"]]
    assert "Custom" in tag_names
    # Default tags still present
    assert "Health" in tag_names
