"""Dashboard authentication — session-cookie-based, independent of API auth."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from agent_gateway.exceptions import AgentGatewayError


class AdminRequiredError(AgentGatewayError):
    """Raised when a non-admin user attempts to access an admin-only dashboard page."""


if TYPE_CHECKING:
    from agent_gateway.config import DashboardAuthConfig


@dataclass
class DashboardUser:
    username: str
    display_name: str = ""
    auth_method: str = "password"
    is_admin: bool = False


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def make_get_dashboard_user(auth_config: DashboardAuthConfig, mount_prefix: str = ""):  # type: ignore[no-untyped-def]
    """Factory: returns a FastAPI dependency configured with the given auth config."""
    login_url = f"{mount_prefix}/dashboard/login"

    async def get_dashboard_user(request: Request) -> DashboardUser:
        if not auth_config.enabled:
            return DashboardUser(username="anonymous", is_admin=True)
        user_id = request.session.get("dashboard_user")
        if not user_id:
            hx = request.headers.get("HX-Request")
            if hx:
                raise HTTPException(
                    status_code=204,
                    headers={"HX-Redirect": login_url},
                )
            raise HTTPException(status_code=302, headers={"Location": login_url})

        # Re-derive admin status from config on every request.
        # This ensures admin access is revoked immediately if credentials change.
        is_admin = (
            auth_config.admin_username is not None and str(user_id) == auth_config.admin_username
        )

        return DashboardUser(
            username=str(user_id),
            display_name=request.session.get("display_name", ""),
            auth_method=request.session.get("auth_method", "password"),
            is_admin=is_admin,
        )

    return get_dashboard_user


def make_require_admin(auth_config: DashboardAuthConfig, mount_prefix: str = ""):  # type: ignore[no-untyped-def]
    """Factory: returns a dependency that enforces admin access."""
    get_user = make_get_dashboard_user(auth_config, mount_prefix=mount_prefix)

    async def require_admin(request: Request) -> DashboardUser:
        current_user: DashboardUser = await get_user(request)
        if not current_user.is_admin:
            hx = request.headers.get("HX-Request")
            if hx:
                raise HTTPException(
                    status_code=403,
                    detail="Admin access required",
                    headers={"HX-Reswap": "none"},
                )
            raise AdminRequiredError()
        return current_user

    return require_admin


def make_login_handler(auth_config: DashboardAuthConfig, mount_prefix: str = ""):  # type: ignore[no-untyped-def]
    """Factory: returns a login POST handler configured with the given auth config."""
    expected_hash = _hash_password(auth_config.password) if auth_config.password else None
    admin_hash = _hash_password(auth_config.admin_password) if auth_config.admin_password else None

    async def login_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> RedirectResponse | dict[str, str]:
        # Validate credentials: admin takes priority, else check regular user
        admin_ok = (
            auth_config.admin_username is not None
            and auth_config.admin_password is not None
            and username == auth_config.admin_username
            and admin_hash is not None
            and _hash_password(password) == admin_hash
        )
        if not admin_ok:
            # Check regular user credentials
            ok = username == auth_config.username
            if expected_hash is not None:
                ok = ok and _hash_password(password) == expected_hash
            if not ok:
                return {"error": "Invalid username or password"}

        request.session["dashboard_user"] = username
        request.session["auth_method"] = "password"
        request.session["display_name"] = username
        # Rotate CSRF token on login
        request.session["csrf_token"] = secrets.token_hex(32)
        return RedirectResponse(url=f"{mount_prefix}/dashboard/", status_code=303)

    return login_post
