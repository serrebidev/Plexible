"""Tests for Plexible updater release targeting."""
from __future__ import annotations


def test_updater_targets_serrebidev_repo():
    from plex_client import updater

    assert updater.GITHUB_OWNER == "serrebidev"
    assert updater.GITHUB_REPO == "Plexible"

