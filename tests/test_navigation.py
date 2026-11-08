"""Tests for lazy expansion in the navigation tree."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

wx = pytest.importorskip("wx")


@pytest.fixture
def tree_setup():
    from plex_client.ui.navigation import NavigationTree

    app = wx.App(False)
    frame = wx.Frame(None)
    release = threading.Event()
    calls = []

    def loader(plex_object):
        calls.append(plex_object)
        release.wait(5)
        return [SimpleNamespace(title=f"Item {i}", type="movie", ratingKey=str(i)) for i in range(3)]

    tree = NavigationTree(frame, loader, lambda _obj: None)
    tree.populate([SimpleNamespace(title="Recently Added", key="/hubs/recent", type="")])
    node, _ = tree.GetFirstChild(tree.GetRootItem())
    yield SimpleNamespace(app=app, tree=tree, node=node, release=release, calls=calls)
    release.set()
    frame.Destroy()
    app.Destroy()


def _labels(tree, item):
    labels = []
    child, cookie = tree.GetFirstChild(item)
    while child and child.IsOk():
        labels.append(tree.GetItemText(child))
        child, cookie = tree.GetNextChild(item, cookie)
    return labels


def _pump_until(app, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.ProcessPendingEvents()
        wx.Yield()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_node_stays_open_on_loading_then_shows_children(tree_setup):
    """One Right arrow is enough even when the server is slow."""
    s = tree_setup
    s.tree.Expand(s.node)
    assert s.tree.IsExpanded(s.node)
    assert _labels(s.tree, s.node) == ["Loading..."]
    s.release.set()
    assert _pump_until(s.app, lambda: _labels(s.tree, s.node) == ["Item 0", "Item 1", "Item 2"])
    assert s.tree.IsExpanded(s.node)


def test_expanding_again_while_loading_does_not_load_twice(tree_setup):
    s = tree_setup
    s.tree.Expand(s.node)
    s.tree.Collapse(s.node)
    s.tree.Expand(s.node)
    s.release.set()
    assert _pump_until(s.app, lambda: len(_labels(s.tree, s.node)) == 3)
    assert len(s.calls) == 1


def test_node_collapsed_during_loading_stays_collapsed(tree_setup):
    """If the user moved on, the tree must not reopen behind their back."""
    s = tree_setup
    s.tree.Expand(s.node)
    s.tree.Collapse(s.node)
    s.release.set()
    assert _pump_until(s.app, lambda: len(_labels(s.tree, s.node)) == 3)
    assert not s.tree.IsExpanded(s.node)
