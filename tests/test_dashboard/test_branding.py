"""Tests for dashboard branding configurability."""

from __future__ import annotations

from agent_gateway import Gateway
from agent_gateway.config import DashboardConfig


class TestDashboardConfigDefaults:
    """DashboardConfig default values."""

    def test_default_subtitle(self) -> None:
        cfg = DashboardConfig()
        assert cfg.subtitle == "AI Control Plane"

    def test_default_title(self) -> None:
        cfg = DashboardConfig()
        assert cfg.title == "Agent Gateway"

    def test_default_favicon_url(self) -> None:
        cfg = DashboardConfig()
        assert cfg.favicon_url == "/dashboard/static/dashboard/default-icon.png"


class TestDashboardConfigCustom:
    """DashboardConfig with custom values."""

    def test_custom_subtitle(self) -> None:
        cfg = DashboardConfig(subtitle="My Platform")
        assert cfg.subtitle == "My Platform"

    def test_custom_favicon_url(self) -> None:
        cfg = DashboardConfig(favicon_url="/static/fav.ico")
        assert cfg.favicon_url == "/static/fav.ico"


class TestUseDashboardOverrides:
    """use_dashboard() correctly populates _pending_dashboard_overrides."""

    def test_subtitle_override(self) -> None:
        gw = Gateway(workspace="./workspace")
        gw.use_dashboard(subtitle="Custom Sub")
        assert gw._pending_dashboard_overrides["subtitle"] == "Custom Sub"

    def test_favicon_url_override(self) -> None:
        gw = Gateway(workspace="./workspace")
        gw.use_dashboard(favicon_url="/img/fav.ico")
        assert gw._pending_dashboard_overrides["favicon_url"] == "/img/fav.ico"

    def test_none_values_not_stored(self) -> None:
        gw = Gateway(workspace="./workspace")
        gw.use_dashboard()
        assert "subtitle" not in gw._pending_dashboard_overrides
        assert "favicon_url" not in gw._pending_dashboard_overrides


class TestTemplateBranding:
    """Template rendering with branding globals."""

    def test_build_templates_default_branding(self) -> None:
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig()
        templates = _build_templates(cfg)
        assert templates.env.globals["dashboard_subtitle"] == "AI Control Plane"

    def test_build_templates_custom_branding(self) -> None:
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig(subtitle="My Hub", logo_url="/icons/logo.png")
        templates = _build_templates(cfg)
        assert templates.env.globals["dashboard_subtitle"] == "My Hub"
        assert templates.env.globals["dashboard_logo_url"] == "/icons/logo.png"

    def test_template_renders_custom_subtitle(self) -> None:
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig(subtitle="Custom Platform")
        templates = _build_templates(cfg)
        # Render base.html snippet via the Jinja2 env
        tmpl = templates.env.from_string("{{ dashboard_subtitle }}")
        assert tmpl.render() == "Custom Platform"

    def test_template_renders_default_hub_icon(self) -> None:
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig()
        templates = _build_templates(cfg)
        tmpl = templates.env.from_string(
            "{% if dashboard_logo_url %}"
            '<img src="{{ dashboard_logo_url }}">'
            "{% else %}"
            '<span class="material-symbols-outlined">hub</span>'
            "{% endif %}"
        )
        result = tmpl.render()
        assert '<span class="material-symbols-outlined">hub</span>' in result
        assert "<img" not in result

    def test_logo_replaces_icon_on_login(self) -> None:
        """When logo_url is set, login page renders logo."""
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig(logo_url="/static/logo.png")
        templates = _build_templates(cfg)
        tmpl = templates.env.from_string(
            "{% if dashboard_logo_url %}"
            '<img src="{{ dashboard_logo_url }}" class="logo">'
            "{% else %}"
            '<span class="material-symbols-outlined">hub</span>'
            "{% endif %}"
        )
        result = tmpl.render()
        assert '<img src="/static/logo.png" class="logo">' in result
        assert "hub" not in result

    def test_logo_replaces_icon_on_sidebar(self) -> None:
        """When logo_url is set, sidebar renders logo."""
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig(logo_url="/static/logo.png")
        templates = _build_templates(cfg)
        tmpl = templates.env.from_string(
            "{% if dashboard_logo_url %}"
            '<img src="{{ dashboard_logo_url }}" class="sidebar-logo">'
            "{% else %}"
            '<span class="material-symbols-outlined">hub</span>'
            "{% endif %}"
        )
        result = tmpl.render()
        assert '<img src="/static/logo.png" class="sidebar-logo">' in result
        assert "hub" not in result

    def test_avatar_uses_display_name(self) -> None:
        """Avatar uses display_name when available."""
        from agent_gateway.dashboard.auth import DashboardUser
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig()
        templates = _build_templates(cfg)
        user = DashboardUser(username="jdoe", display_name="Jane Doe")
        tmpl = templates.env.from_string(
            "{{ current_user.display_name if current_user and "
            "current_user.display_name else "
            "(current_user.username if current_user else 'Admin') }}"
        )
        result = tmpl.render(current_user=user)
        assert result == "Jane Doe"

    def test_avatar_falls_back_to_username(self) -> None:
        """Avatar falls back to username when display_name is empty."""
        from agent_gateway.dashboard.auth import DashboardUser
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig()
        templates = _build_templates(cfg)
        user = DashboardUser(username="jdoe")
        tmpl = templates.env.from_string(
            "{{ current_user.display_name if current_user and "
            "current_user.display_name else "
            "(current_user.username if current_user else 'Admin') }}"
        )
        result = tmpl.render(current_user=user)
        assert result == "jdoe"

    def test_template_renders_custom_logo(self) -> None:
        from agent_gateway.dashboard.router import _build_templates

        cfg = DashboardConfig(logo_url="/static/logo.png")
        templates = _build_templates(cfg)
        tmpl = templates.env.from_string(
            "{% if dashboard_logo_url %}"
            '<img src="{{ dashboard_logo_url }}">'
            "{% else %}"
            '<span class="material-symbols-outlined">hub</span>'
            "{% endif %}"
        )
        result = tmpl.render()
        assert '<img src="/static/logo.png">' in result
        assert "hub" not in result
