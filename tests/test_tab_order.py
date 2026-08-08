"""Keyboard traversal regression tests.

These encode the wxWidgets rule that a container exposes two different
decisions, and that conflating them silently empties the Tab cycle:

    AcceptsFocus()             -- may this panel hold focus itself?
    AcceptsFocusFromKeyboard() -- should Tab descend into this panel?

A container that answers False to the second is skipped whole, children
included, so every control inside becomes unreachable by keyboard.
"""
from __future__ import annotations

import pytest

wx_available = False
try:
    import wx

    wx_available = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(not wx_available, reason="wxPython not available")


@pytest.fixture
def app():
    application = wx.App(False)
    yield application


@pytest.fixture
def frame(app):
    top = wx.Frame(None)
    yield top
    top.Destroy()


def in_tab_cycle(w):
    """The predicate wx actually uses.

    Confirmed with wx.UIActionSimulator against the real frame: a panel
    reporting AcceptsFocusFromKeyboard() True took and trapped the focus even
    though AcceptsFocus() returned False, and left the cycle only once this
    returned False. AcceptsFocus() alone does not govern traversal.
    """
    return w.AcceptsFocusFromKeyboard() and w.IsShown() and w.IsEnabled()


def has_focusable_child(w):
    return any(in_tab_cycle(c) for c in w.GetChildren())


class TestNonFocusableContainers:
    def test_decorative_panel_is_out_of_the_cycle(self, frame):
        """A decorative strip must not join the cycle at all.

        Asserting on AcceptsFocusFromKeyboard is the point: an earlier fix
        overrode only AcceptsFocus, which left this True and kept the panel a
        tab stop that Tab could not escape.
        """
        from plex_client.ui.content_panel import DecorativePanel

        accent = DecorativePanel(frame, size=(-1, 2))
        assert accent.AcceptsFocusFromKeyboard() is False
        assert in_tab_cycle(accent) is False

    def test_plain_panel_would_trap_tab(self, frame):
        """Guards the premise: a bare wx.Panel with no focusable child is a stop."""
        bare = wx.Panel(frame, size=(-1, 2))
        assert in_tab_cycle(bare) is True
        assert has_focusable_child(bare) is False

    def test_container_still_forwards_tab_to_children(self, frame):
        """The regression: blocking the descend hook made children unreachable."""
        from plex_client.ui.content_panel import TransparentContainer

        container = TransparentContainer(frame)
        inner = wx.TextCtrl(container)

        assert container.AcceptsFocusFromKeyboard() is True
        assert has_focusable_child(container) is True
        assert in_tab_cycle(inner) is True

    def test_container_drops_out_when_children_are_hidden(self, frame):
        """Nothing focusable inside -> the container leaves the cycle entirely."""
        from plex_client.ui.content_panel import TransparentContainer

        container = TransparentContainer(frame)
        hidden = wx.ListBox(container)
        hidden.Hide()
        wx.StaticText(container, label="Sign in to see your queue.")

        assert container.AcceptsFocusFromKeyboard() is False
        assert in_tab_cycle(container) is False

    def test_container_ignores_disabled_children(self, frame):
        """All transport buttons disabled -> the playback panel is not a stop."""
        from plex_client.ui.content_panel import TransparentContainer

        container = TransparentContainer(frame)
        button = wx.Button(container, label="Play")
        button.Disable()

        assert container.AcceptsFocusFromKeyboard() is False

    def test_container_never_holds_focus_itself(self, frame):
        from plex_client.ui.content_panel import TransparentContainer

        container = TransparentContainer(frame)
        wx.TextCtrl(container)
        assert container.AcceptsFocus() is False


class TestAccessibleNames:
    def test_name_control_exposes_name_via_msaa(self, frame):
        """SetName alone does not reach MSAA for native controls."""
        from plex_client.ui.content_panel import name_control

        tree = wx.TreeCtrl(frame)
        accessible = name_control(tree, "Library Navigation", "tree")

        assert tree.GetName() == "Library Navigation"
        assert accessible.GetName(0) == (wx.ACC_OK, "Library Navigation")
        assert accessible.GetRole(0) == (wx.ACC_OK, wx.ROLE_SYSTEM_OUTLINE)

    def test_slider_role_is_mapped(self, frame):
        from plex_client.ui.content_panel import name_control

        slider = wx.Slider(frame)
        accessible = name_control(slider, "Volume", "slider")
        assert accessible.GetRole(0) == (wx.ACC_OK, wx.ROLE_SYSTEM_SLIDER)
