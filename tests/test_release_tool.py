"""Tests for release helper behavior."""
from __future__ import annotations


def test_collect_commits_skips_merges_and_duplicate_subjects(monkeypatch):
    from tools import release_tool

    captured_args = {}

    def fake_run_git(*args: str) -> str:
        captured_args["args"] = args
        return "Fix updater\x1fbody\x1eFix updater\x1fduplicate\x1eAdd release docs\x1f\x1e"

    monkeypatch.setattr(release_tool, "_run_git", fake_run_git)

    commits = release_tool._collect_commits("v1.0.0..HEAD")

    assert "--no-merges" in captured_args["args"]
    assert commits == [("Fix updater", "body"), ("Add release docs", "")]

