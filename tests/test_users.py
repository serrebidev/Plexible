"""Tests for PlexService user/sharing management features."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestUserManagement:
    """Test user and sharing management functionality."""

    def test_users(self, plex_service, mock_account):
        """Test getting list of users."""
        user = MagicMock()
        user.username = "friend1"
        mock_account.users.return_value = [user]
        
        users = plex_service.users()
        
        assert len(users) == 1
        mock_account.users.assert_called_once()

    def test_user_by_username(self, plex_service, mock_account):
        """Test getting a specific user."""
        user = MagicMock()
        user.username = "friend1"
        mock_account.user.return_value = user
        
        result = plex_service.user("friend1")
        
        assert result == user
        mock_account.user.assert_called_once_with("friend1")

    def test_invite_friend(self, plex_service, mock_account, mock_server, mock_library_section):
        """Test inviting a friend."""
        plex_service.invite_friend(
            user="friend@example.com",
            server=mock_server,
            sections=[mock_library_section],
            allow_sync=True,
        )
        
        mock_account.inviteFriend.assert_called_once()

    def test_invite_friend_default_server(self, plex_service, mock_account):
        """Test inviting a friend using default server."""
        plex_service.invite_friend(user="friend@example.com")
        
        mock_account.inviteFriend.assert_called_once()

    def test_remove_friend(self, plex_service, mock_account):
        """Test removing a friend."""
        plex_service.remove_friend("friend@example.com")
        
        mock_account.removeFriend.assert_called_once_with("friend@example.com")

    def test_update_friend(self, plex_service, mock_account, mock_library_section):
        """Test updating friend's access."""
        plex_service.update_friend(
            user="friend@example.com",
            sections=[mock_library_section],
            allow_sync=False,
        )
        
        mock_account.updateFriend.assert_called_once()

    def test_pending_invites(self, plex_service, mock_account):
        """Test getting pending invites."""
        invite = MagicMock()
        mock_account.pendingInvites.return_value = [invite]
        
        invites = plex_service.pending_invites()
        
        assert len(invites) == 1
        mock_account.pendingInvites.assert_called_once_with(
            includeSent=True,
            includeReceived=True,
        )

    def test_pending_invites_sent_only(self, plex_service, mock_account):
        """Test getting sent invites only."""
        plex_service.pending_invites(include_sent=True, include_received=False)
        
        mock_account.pendingInvites.assert_called_once_with(
            includeSent=True,
            includeReceived=False,
        )

    def test_accept_invite(self, plex_service, mock_account):
        """Test accepting an invite."""
        plex_service.accept_invite("inviter@example.com")
        
        mock_account.acceptInvite.assert_called_once_with("inviter@example.com")

    def test_cancel_invite(self, plex_service, mock_account):
        """Test canceling an invite."""
        plex_service.cancel_invite("friend@example.com")
        
        mock_account.cancelInvite.assert_called_once_with("friend@example.com")


class TestHomeUserManagement:
    """Test home user management functionality."""

    def test_create_home_user(self, plex_service, mock_account, mock_library_section):
        """Test creating a home user."""
        plex_service.create_home_user(
            user="Kid",
            sections=[mock_library_section],
            allow_sync=False,
        )
        
        mock_account.createHomeUser.assert_called_once()

    def test_remove_home_user(self, plex_service, mock_account):
        """Test removing a home user."""
        plex_service.remove_home_user("Kid")
        
        mock_account.removeHomeUser.assert_called_once_with("Kid")

    def test_switch_home_user(self, plex_service, mock_account):
        """Test switching to a home user."""
        new_account = MagicMock()
        mock_account.switchHomeUser.return_value = new_account
        
        result = plex_service.switch_home_user("Kid", pin="1234")
        
        assert result == new_account
        mock_account.switchHomeUser.assert_called_once_with("Kid", pin="1234")

    def test_switch_server_user(self, plex_service, mock_server):
        """Test switching user on server."""
        new_server = MagicMock()
        mock_server.switchUser.return_value = new_server
        
        result = plex_service.switch_server_user("Kid")
        
        assert result == new_server
        mock_server.switchUser.assert_called_once()
