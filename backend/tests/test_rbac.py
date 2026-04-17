"""
Unit tests for RBAC logic.

Covers:
  - role_gte()           — backend/app/services/rbac.py
  - resolve_role()       — backend/app/services/rbac.py
  - _check_last_owner()  — backend/app/api/rbac_routes.py
  - require_role()       — backend/app/api/auth_helpers.py

All external dependencies (Databricks SDK, httpx network calls, database)
are mocked — tests run without any infrastructure.
Stubs for heavy third-party packages live in conftest.py and are applied
before any app.* module is imported.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.rbac as rbac_module
from app.services.rbac import role_gte, resolve_role, _role_cache, _admin_cache

import app.api.rbac_routes as rbac_routes_module  # noqa: F401 — ensures router registered
from app.api.rbac_routes import _check_last_owner

import app.api.auth_helpers as auth_helpers_module  # noqa: F401
from app.api.auth_helpers import require_role


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_rbac_caches():
    """Wipe in-process caches before and after every test."""
    _admin_cache.clear()
    _role_cache.clear()
    yield
    _admin_cache.clear()
    _role_cache.clear()


def _make_request(headers: dict) -> MagicMock:
    """Return a minimal FastAPI Request-like mock with the given headers."""
    req = MagicMock()
    req.headers = headers
    return req


# ===========================================================================
# 1.  role_gte()
# ===========================================================================

class TestRoleGte:
    def test_use_gte_use(self):
        assert role_gte("use", "use") is True

    def test_manage_gte_use(self):
        assert role_gte("manage", "use") is True

    def test_manage_gte_manage(self):
        assert role_gte("manage", "manage") is True

    def test_owner_gte_use(self):
        assert role_gte("owner", "use") is True

    def test_owner_gte_manage(self):
        assert role_gte("owner", "manage") is True

    def test_owner_gte_owner(self):
        assert role_gte("owner", "owner") is True

    def test_use_not_gte_manage(self):
        assert role_gte("use", "manage") is False

    def test_use_not_gte_owner(self):
        assert role_gte("use", "owner") is False

    def test_manage_not_gte_owner(self):
        assert role_gte("manage", "owner") is False

    def test_unknown_role_as_a_is_false(self):
        # Unknown role maps to hierarchy 0 — not >= any real role
        assert role_gte("superadmin", "use") is False

    def test_unknown_role_as_b_is_true(self):
        # Any real role is >= unknown (which maps to 0)
        assert role_gte("use", "unknown_role") is True

    def test_both_unknown_roles_are_equal(self):
        # 0 >= 0
        assert role_gte("ghost", "phantom") is True


# ===========================================================================
# 2.  resolve_role()
# ===========================================================================

class TestResolveRole:
    @pytest.mark.asyncio
    async def test_workspace_admin_returns_owner(self):
        with patch.object(rbac_module, "is_workspace_admin", new=AsyncMock(return_value=True)):
            role = await resolve_role("admin@example.com", "tok", "https://ws.example.com")
        assert role == "owner"

    @pytest.mark.asyncio
    async def test_explicit_assignment_overrides_default(self):
        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="manage")

        with patch.object(rbac_module, "is_workspace_admin", new=AsyncMock(return_value=False)), \
             patch("app.services.database.db_service", mock_db):
            role = await resolve_role("manager@example.com", "tok", "https://ws.example.com")

        assert role == "manage"

    @pytest.mark.asyncio
    async def test_unassigned_user_gets_use(self):
        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value=None)

        with patch.object(rbac_module, "is_workspace_admin", new=AsyncMock(return_value=False)), \
             patch("app.services.database.db_service", mock_db):
            role = await resolve_role("nobody@example.com", "tok", "https://ws.example.com")

        assert role == "use"

    @pytest.mark.asyncio
    async def test_no_db_service_defaults_to_use(self):
        with patch.object(rbac_module, "is_workspace_admin", new=AsyncMock(return_value=False)), \
             patch("app.services.database.db_service", None):
            role = await resolve_role("user@example.com", "tok", "https://ws.example.com")

        assert role == "use"

    @pytest.mark.asyncio
    async def test_second_call_uses_role_cache(self):
        """DB must be queried exactly once; the second call must hit the cache."""
        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="manage")

        with patch.object(rbac_module, "is_workspace_admin", new=AsyncMock(return_value=False)), \
             patch("app.services.database.db_service", mock_db):
            role1 = await resolve_role("cached@example.com", "tok", "https://ws.example.com")
            role2 = await resolve_role("cached@example.com", "tok", "https://ws.example.com")

        assert role1 == role2 == "manage"
        mock_db.get_user_role.assert_called_once()

    @pytest.mark.asyncio
    async def test_pre_seeded_cache_skips_db(self):
        """A valid cache entry must be returned without touching the database."""
        identity = "preseeded@example.com"
        _role_cache[identity] = ("owner", time.monotonic() + 9999)

        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="use")

        with patch.object(rbac_module, "is_workspace_admin", new=AsyncMock(return_value=False)), \
             patch("app.services.database.db_service", mock_db):
            role = await resolve_role(identity, "tok", "https://ws.example.com")

        assert role == "owner"
        mock_db.get_user_role.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_cache_entry_re_queries_db(self):
        """An expired cache entry must not be returned; DB must be consulted."""
        identity = "stale@example.com"
        _role_cache[identity] = ("owner", time.monotonic() - 1)  # already expired

        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="use")

        with patch.object(rbac_module, "is_workspace_admin", new=AsyncMock(return_value=False)), \
             patch("app.services.database.db_service", mock_db):
            role = await resolve_role(identity, "tok", "https://ws.example.com")

        assert role == "use"
        mock_db.get_user_role.assert_called_once()


# ===========================================================================
# 3.  _check_last_owner()
# ===========================================================================

class TestCheckLastOwner:
    @pytest.mark.asyncio
    async def test_removing_last_owner_raises_409(self):
        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="owner")
        mock_db.count_owners = AsyncMock(return_value=1)

        from fastapi import HTTPException
        with patch("app.services.database.db_service", mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await _check_last_owner("only-owner@example.com", new_role=None)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_removing_non_owner_does_not_check_count(self):
        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="manage")
        mock_db.count_owners = AsyncMock(return_value=1)

        with patch("app.services.database.db_service", mock_db):
            await _check_last_owner("manager@example.com", new_role=None)

        mock_db.count_owners.assert_not_called()

    @pytest.mark.asyncio
    async def test_downgrading_last_owner_raises_409(self):
        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="owner")
        mock_db.count_owners = AsyncMock(return_value=1)

        from fastapi import HTTPException
        with patch("app.services.database.db_service", mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await _check_last_owner("only-owner@example.com", new_role="manage")

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_downgrading_owner_when_multiple_owners_succeeds(self):
        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="owner")
        mock_db.count_owners = AsyncMock(return_value=2)

        with patch("app.services.database.db_service", mock_db):
            await _check_last_owner("one-of-many@example.com", new_role="manage")

    @pytest.mark.asyncio
    async def test_reassigning_owner_to_owner_does_not_check_count(self):
        """new_role='owner' on an existing owner must never raise."""
        mock_db = MagicMock()
        mock_db.get_user_role = AsyncMock(return_value="owner")
        mock_db.count_owners = AsyncMock(return_value=1)

        with patch("app.services.database.db_service", mock_db):
            await _check_last_owner("solo-owner@example.com", new_role="owner")

        mock_db.count_owners.assert_not_called()


# ===========================================================================
# 4.  require_role()
# ===========================================================================

class TestRequireRole:
    # require_role() resolves dependencies via local imports at call time:
    #   from app.services.rbac import resolve_role, role_gte
    #   from app.api.config_store import get_effective_setting
    #   from app.config import get_settings
    # So patches must target those source locations, not app.api.auth_helpers.

    @pytest.mark.asyncio
    async def test_no_token_and_no_email_raises_401(self):
        req = _make_request({})

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_role(req, "use")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_insufficient_role_raises_403(self):
        req = _make_request({
            "X-Forwarded-Access-Token": "user-token",
            "X-Forwarded-Email": "viewer@example.com",
        })

        with patch.object(rbac_module, "resolve_role", new=AsyncMock(return_value="use")), \
             patch("app.api.config_store.get_effective_setting", return_value=""), \
             patch("app.config.get_settings",
                   return_value=MagicMock(databricks_host="")):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await require_role(req, "manage")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_sufficient_role_returns_identity_token_role(self):
        req = _make_request({
            "X-Forwarded-Access-Token": "user-token",
            "X-Forwarded-Email": "manager@example.com",
        })

        with patch.object(rbac_module, "resolve_role", new=AsyncMock(return_value="manage")), \
             patch("app.api.config_store.get_effective_setting", return_value=""), \
             patch("app.config.get_settings",
                   return_value=MagicMock(databricks_host="")):
            identity, token, role = await require_role(req, "manage")

        assert identity == "manager@example.com"
        assert token == "user-token"
        assert role == "manage"

    @pytest.mark.asyncio
    async def test_owner_satisfies_manage_requirement(self):
        req = _make_request({
            "X-Forwarded-Access-Token": "owner-token",
            "X-Forwarded-Email": "owner@example.com",
        })

        with patch.object(rbac_module, "resolve_role", new=AsyncMock(return_value="owner")), \
             patch("app.api.config_store.get_effective_setting", return_value=""), \
             patch("app.config.get_settings",
                   return_value=MagicMock(databricks_host="")):
            identity, token, role = await require_role(req, "manage")

        assert role == "owner"

    @pytest.mark.asyncio
    async def test_email_only_no_token_resolves_role(self):
        """Email present but no bearer token — identity resolved, no 401 raised."""
        req = _make_request({"X-Forwarded-Email": "dbuser@example.com"})

        with patch.object(rbac_module, "resolve_role", new=AsyncMock(return_value="use")), \
             patch("app.api.config_store.get_effective_setting", return_value=""), \
             patch("app.config.get_settings",
                   return_value=MagicMock(databricks_host="")):
            identity, token, role = await require_role(req, "use")

        assert identity == "dbuser@example.com"
        assert token == ""
        assert role == "use"

    @pytest.mark.asyncio
    async def test_authorization_bearer_header_accepted(self):
        """Direct API clients sending Authorization: Bearer are accepted."""
        req = _make_request({
            "Authorization": "Bearer direct-api-token",
            "X-Forwarded-Email": "apiuser@example.com",
        })

        with patch.object(rbac_module, "resolve_role", new=AsyncMock(return_value="use")), \
             patch("app.api.config_store.get_effective_setting", return_value=""), \
             patch("app.config.get_settings",
                   return_value=MagicMock(databricks_host="")):
            identity, token, role = await require_role(req, "use")

        assert token == "direct-api-token"
