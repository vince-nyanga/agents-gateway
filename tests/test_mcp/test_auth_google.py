"""Tests for mcp/auth_google.py -- Google service account token provider."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from agent_gateway.exceptions import McpAuthError

# Skip entire module if google-auth is not installed
pytest.importorskip("google.oauth2.service_account")


from agent_gateway.mcp.auth_google import GoogleServiceAccountProvider  # noqa: E402


def _make_mock_credentials(
    token: str | None = "mock-token",
    valid: bool = True,
    expiry_offset: float = 600.0,
) -> MagicMock:
    """Build a mock google.oauth2.service_account.Credentials."""
    cred = MagicMock()
    cred.valid = valid
    cred.token = token
    expiry = MagicMock()
    expiry.timestamp.return_value = time.time() + expiry_offset
    cred.expiry = expiry
    cred.refresh = MagicMock()
    return cred


class TestGoogleServiceAccountProvider:
    @patch("agent_gateway.mcp.auth_google.sa")
    def _make_provider(
        self,
        mock_sa: MagicMock,
        mock_cred: MagicMock | None = None,
    ) -> GoogleServiceAccountProvider:
        cred = mock_cred or _make_mock_credentials()
        mock_sa.Credentials.from_service_account_info.return_value = cred
        provider = GoogleServiceAccountProvider(
            server_name="gcp-srv",
            service_account_info={"type": "service_account"},
            scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        return provider

    async def test_get_token_cached(self) -> None:
        """When token is valid and not near expiry, return cached token."""
        mock_cred = _make_mock_credentials(token="cached-tok", valid=True, expiry_offset=600)
        with patch("agent_gateway.mcp.auth_google.sa") as mock_sa:
            mock_sa.Credentials.from_service_account_info.return_value = mock_cred
            provider = GoogleServiceAccountProvider(
                server_name="gcp-srv",
                service_account_info={"type": "service_account"},
                scopes=["scope"],
            )
            token = await provider.get_token()
        assert token == "cached-tok"
        mock_cred.refresh.assert_not_called()

    async def test_proactive_refresh(self) -> None:
        """Refresh triggered when within buffer window."""
        mock_cred = _make_mock_credentials(
            token="old-tok",
            valid=True,
            expiry_offset=60,  # < _REFRESH_BUFFER_SECONDS
        )

        # After refresh, update token
        def do_refresh(req: object) -> None:
            mock_cred.token = "new-tok"

        mock_cred.refresh.side_effect = do_refresh

        with (
            patch("agent_gateway.mcp.auth_google.sa") as mock_sa,
            patch("agent_gateway.mcp.auth_google.google_requests"),
        ):
            mock_sa.Credentials.from_service_account_info.return_value = mock_cred
            provider = GoogleServiceAccountProvider(
                server_name="gcp-srv",
                service_account_info={"type": "service_account"},
                scopes=["scope"],
            )
            token = await provider.get_token()
        assert token == "new-tok"
        mock_cred.refresh.assert_called_once()

    async def test_refresh_failure_raises_mcp_auth_error(self) -> None:
        mock_cred = _make_mock_credentials(valid=False, token=None)
        mock_cred.refresh.side_effect = Exception("Network error")

        with (
            patch("agent_gateway.mcp.auth_google.sa") as mock_sa,
            patch("agent_gateway.mcp.auth_google.google_requests"),
        ):
            mock_sa.Credentials.from_service_account_info.return_value = mock_cred
            provider = GoogleServiceAccountProvider(
                server_name="gcp-srv",
                service_account_info={"type": "service_account"},
                scopes=["scope"],
            )
            with pytest.raises(McpAuthError, match="Google SA token refresh failed"):
                await provider.get_token()

    async def test_none_token_after_refresh_raises_mcp_auth_error(self) -> None:
        mock_cred = _make_mock_credentials(valid=False, token=None)

        def do_refresh(req: object) -> None:
            mock_cred.token = None  # stays None after refresh

        mock_cred.refresh.side_effect = do_refresh

        with (
            patch("agent_gateway.mcp.auth_google.sa") as mock_sa,
            patch("agent_gateway.mcp.auth_google.google_requests"),
        ):
            mock_sa.Credentials.from_service_account_info.return_value = mock_cred
            provider = GoogleServiceAccountProvider(
                server_name="gcp-srv",
                service_account_info={"type": "service_account"},
                scopes=["scope"],
            )
            with pytest.raises(McpAuthError, match="token is None after refresh"):
                await provider.get_token()


class TestGoogleImportError:
    def test_import_error_when_google_auth_missing(self) -> None:
        """Clear ImportError when google-auth not installed."""
        with (
            patch("agent_gateway.mcp.auth_google.sa", None),
            pytest.raises(ImportError, match="google-auth is required"),
        ):
            GoogleServiceAccountProvider(
                server_name="gcp-srv",
                service_account_info={"type": "service_account"},
                scopes=["scope"],
            )
