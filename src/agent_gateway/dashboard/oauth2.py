"""Dashboard OAuth2/OIDC login — Authorization Code flow with confidential client."""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx
from fastapi import Request
from fastapi.responses import RedirectResponse

if TYPE_CHECKING:
    from agent_gateway.config import DashboardOAuth2Config

logger = logging.getLogger(__name__)

_ALLOWED_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"})
_CACHE_TTL = 3600.0  # 1 hour


class OIDCDiscoveryClient:
    def __init__(self, issuer: str) -> None:
        self._issuer = issuer.rstrip("/")
        self._http = httpx.AsyncClient(timeout=10.0)
        self._discovery_cache: dict[str, Any] | None = None
        self._discovery_fetched_at: float = 0.0
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0

    async def discover(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._discovery_cache and (now - self._discovery_fetched_at) < _CACHE_TTL:
            return self._discovery_cache
        resp = await self._http.get(f"{self._issuer}/.well-known/openid-configuration")
        resp.raise_for_status()
        self._discovery_cache = resp.json()
        self._discovery_fetched_at = time.monotonic()
        return self._discovery_cache

    async def fetch_jwks(self, jwks_uri: str) -> dict[str, Any]:
        now = time.monotonic()
        if self._jwks_cache and (now - self._jwks_fetched_at) < _CACHE_TTL:
            return self._jwks_cache
        resp = await self._http.get(jwks_uri)
        resp.raise_for_status()
        self._jwks_cache = resp.json()
        self._jwks_fetched_at = time.monotonic()
        return self._jwks_cache

    async def close(self) -> None:
        await self._http.aclose()


def _make_login_redirect(mount_prefix: str = "") -> Callable[[str], RedirectResponse]:
    def _login_redirect(error: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{mount_prefix}/dashboard/login?error={error}",
            status_code=303,
        )

    return _login_redirect


def make_authorize_handler(
    config: DashboardOAuth2Config,
    discovery: OIDCDiscoveryClient,
    mount_prefix: str = "",
) -> Any:
    _login_redirect = _make_login_redirect(mount_prefix)

    async def authorize(request: Request) -> RedirectResponse:
        try:
            doc = await discovery.discover()
        except Exception:
            logger.warning("OIDC discovery failed", exc_info=True)
            return _login_redirect("SSO configuration error")

        authorization_endpoint = doc.get("authorization_endpoint")
        if not authorization_endpoint:
            logger.warning("No authorization_endpoint in OIDC discovery")
            return _login_redirect("SSO configuration error")

        state = secrets.token_hex(32)
        request.session["oauth2_state"] = state

        redirect_uri = str(request.url_for("oauth2_callback"))
        params = urlencode(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(config.scopes),
                "state": state,
            }
        )
        return RedirectResponse(url=f"{authorization_endpoint}?{params}", status_code=303)

    return authorize


def make_callback_handler(
    config: DashboardOAuth2Config,
    discovery: OIDCDiscoveryClient,
    mount_prefix: str = "",
) -> Any:
    _login_redirect = _make_login_redirect(mount_prefix)

    async def callback(request: Request) -> RedirectResponse:
        import jwt as pyjwt
        from jwt import PyJWK

        # Validate state
        state = request.query_params.get("state", "")
        expected_state = request.session.pop("oauth2_state", None)
        if not state or state != expected_state:
            logger.warning("OAuth2 callback: state mismatch")
            return _login_redirect("Invalid SSO state")

        # Check for error from provider
        error = request.query_params.get("error")
        if error:
            desc = request.query_params.get("error_description", error)
            logger.warning("OAuth2 callback error from provider: %s", desc)
            return _login_redirect("SSO login failed")

        code = request.query_params.get("code", "")
        if not code:
            logger.warning("OAuth2 callback: missing authorization code")
            return _login_redirect("SSO login failed")

        # Discover endpoints
        try:
            doc = await discovery.discover()
        except Exception:
            logger.warning("OIDC discovery failed during callback", exc_info=True)
            return _login_redirect("SSO configuration error")

        token_endpoint = doc.get("token_endpoint")
        if not token_endpoint:
            logger.warning("No token_endpoint in OIDC discovery")
            return _login_redirect("SSO configuration error")

        # Exchange code for tokens
        redirect_uri = str(request.url_for("oauth2_callback"))
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                token_resp = await client.post(
                    token_endpoint,
                    data={
                        "grant_type": "authorization_code",
                        "client_id": config.client_id,
                        "client_secret": config.client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                )
                token_resp.raise_for_status()
                token_data = token_resp.json()
        except Exception:
            logger.warning("Token exchange failed", exc_info=True)
            return _login_redirect("SSO token exchange failed")

        id_token = token_data.get("id_token")
        if not id_token:
            logger.warning("No id_token in token response")
            return _login_redirect("SSO login failed")

        # Validate id_token JWT
        try:
            header = pyjwt.get_unverified_header(id_token)
            alg = header.get("alg", "")
            if alg not in _ALLOWED_ALGORITHMS:
                logger.warning("Disallowed JWT algorithm: %s", alg)
                return _login_redirect("SSO login failed")

            kid = header.get("kid")
            jwks_uri = doc.get("jwks_uri")
            if not jwks_uri:
                logger.warning("No jwks_uri in OIDC discovery")
                return _login_redirect("SSO configuration error")

            jwks_data = await discovery.fetch_jwks(jwks_uri)
            keys = jwks_data.get("keys", [])

            # Find matching key
            public_key = None
            for key_data in keys:
                if kid and key_data.get("kid") != kid:
                    continue
                jwk = PyJWK(key_data)
                public_key = jwk.key
                break

            if public_key is None:
                logger.warning("No matching JWKS key for kid=%s", kid)
                return _login_redirect("SSO login failed")

            claims = pyjwt.decode(
                id_token,
                key=public_key,
                algorithms=list(_ALLOWED_ALGORITHMS),
                audience=config.client_id,
                issuer=config.issuer.rstrip("/"),
                options={"require": ["exp", "iss", "aud"]},
            )
        except pyjwt.ExpiredSignatureError:
            logger.warning("OAuth2 callback: id_token expired")
            return _login_redirect("SSO token expired")
        except (pyjwt.InvalidAudienceError, pyjwt.InvalidIssuerError) as exc:
            logger.warning("OAuth2 callback: id_token validation failed: %s", exc)
            return _login_redirect("SSO login failed")
        except pyjwt.PyJWTError as exc:
            logger.warning("OAuth2 callback: JWT error: %s", exc)
            return _login_redirect("SSO login failed")
        except Exception:
            logger.warning("OAuth2 callback: unexpected error validating id_token", exc_info=True)
            return _login_redirect("SSO login failed")

        # Extract user info from claims
        email = claims.get("email")
        name = claims.get("name", "")
        sub = claims.get("sub", "")

        # Fallback to userinfo endpoint if email not in token
        if not email:
            userinfo_endpoint = doc.get("userinfo_endpoint")
            access_token = token_data.get("access_token")
            if userinfo_endpoint and access_token:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        ui_resp = await client.get(
                            userinfo_endpoint,
                            headers={"Authorization": f"Bearer {access_token}"},
                        )
                        ui_resp.raise_for_status()
                        userinfo = ui_resp.json()
                        email = userinfo.get("email") or email
                        name = name or userinfo.get("name", "")
                except Exception:
                    logger.warning("Userinfo fetch failed", exc_info=True)

        # DISCARD all tokens — never stored, never sent to browser
        # Store session data
        username = email or sub
        request.session["dashboard_user"] = username
        request.session["display_name"] = name
        request.session["auth_method"] = "oauth2"
        request.session["csrf_token"] = secrets.token_hex(32)

        return RedirectResponse(url=f"{mount_prefix}/dashboard/", status_code=303)

    return callback
