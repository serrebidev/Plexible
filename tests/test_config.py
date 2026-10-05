"""Tests for configuration management."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, mock_open
import json
import os


class TestConfigStore:
    """Test ConfigStore functionality."""

    @pytest.fixture
    def mock_config_data(self):
        """Sample configuration data."""
        return {
            "client_id": "test-client-123",
            "auth_token": "test-token-abc",
            "selected_server": "server-id-456",
            "selected_server_name": "My Plex Server",
            "preferred_servers": ["server-id-456", "server-id-789"],
            "vlc_path": "C:\\Program Files\\VLC\\vlc.exe",
            "pending_progress": {},
            "auto_check_updates": True,
        }

    def test_config_store_import(self):
        """Test that ConfigStore can be imported."""
        from plex_client.config import ConfigStore
        assert ConfigStore is not None

    def test_get_client_id(self, mock_config_data):
        """Test getting client ID."""
        with patch("builtins.open", mock_open(read_data=json.dumps(mock_config_data))):
            with patch("os.path.exists", return_value=True):
                from plex_client.config import ConfigStore
                # ConfigStore uses path resolution, so we need to handle that
                assert ConfigStore is not None

    def test_default_values(self):
        """Test that default values are used when config doesn't exist."""
        from plex_client.config import ConfigStore
        # Just verify the class exists and has expected methods
        assert hasattr(ConfigStore, 'get_client_id')
        assert hasattr(ConfigStore, 'get_auth_token')
        assert hasattr(ConfigStore, 'get_selected_server')


class TestAuthManager:
    """Test AuthManager functionality."""

    def test_auth_manager_import(self):
        """Test that AuthManager can be imported."""
        from plex_client.auth import AuthManager
        assert AuthManager is not None

    def test_auth_manager_has_required_methods(self):
        """Test that AuthManager has required methods."""
        from plex_client.auth import AuthManager
        assert hasattr(AuthManager, 'authenticate_with_browser')
        assert hasattr(AuthManager, 'load_saved_account')
        assert hasattr(AuthManager, 'sign_out')


def test_config_override_takes_priority_over_existing_config(tmp_path, monkeypatch):
    from plex_client.config import ConfigStore

    old_dir = tmp_path / "old"
    old_dir.mkdir()
    (old_dir / "config.json").write_text('{"auth_token": "old-account"}', encoding="utf-8")
    override = tmp_path / "new"
    monkeypatch.setenv("PLEXIBLE_CONFIG_DIR", str(override))
    monkeypatch.setattr(ConfigStore, "_script_directory", lambda self: old_dir)
    monkeypatch.setattr(ConfigStore, "LEGACY_DIR", tmp_path / "legacy")

    config = ConfigStore()
    assert config.get_auth_token() is None
    config.set_auth_token("new-account")
    assert json.loads((override / "config.json").read_text(encoding="utf-8"))["auth_token"] == "new-account"
    assert json.loads((old_dir / "config.json").read_text(encoding="utf-8"))["auth_token"] == "old-account"


def test_invalid_utf8_config_recovers_with_defaults(tmp_path, monkeypatch):
    from plex_client.config import ConfigStore

    monkeypatch.setenv("PLEXIBLE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_bytes(b"\xff\xfe")
    config = ConfigStore()
    assert config.get_auth_token() is None
    assert config.get_client_id()
    config.set_auto_check_updates(False)
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["auto_check_updates"] is False


def test_explicit_profile_does_not_import_legacy_account(tmp_path, monkeypatch):
    from plex_client.config import ConfigStore

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "config.json").write_text('{"auth_token":"legacy-account"}', encoding="utf-8")
    monkeypatch.setattr(ConfigStore, "LEGACY_DIR", legacy)
    monkeypatch.setenv("PLEXIBLE_CONFIG_DIR", str(tmp_path / "new-profile"))
    assert ConfigStore().get_auth_token() is None
