from __future__ import annotations

from typing import Optional

import wx

from plexapi.base import PlexObject

from ..plex_service import PlayableMedia


class MetadataPanel(wx.Panel):
    """Shows primary metadata for the selected Plex object along with actions."""

    def __init__(self, parent: wx.Window, on_play: callable[[PlayableMedia], None]) -> None:
        super().__init__(parent)
        self._on_play = on_play
        self._title = wx.StaticText(self, label="Select an item to see details.")
        bold_font = self._title.GetFont()
        bold_font.SetPointSize(bold_font.GetPointSize() + 2)
        bold_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self._title.SetFont(bold_font)

        self._type_label = wx.StaticText(self, label="")
        self._summary = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE)
        self._summary.SetMinSize((200, 120))
        self._play_button = wx.Button(self, label="Play")
        self._play_button.Disable()
        self._play_button.Bind(wx.EVT_BUTTON, self._handle_play)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._title, 0, wx.ALL | wx.EXPAND, 8)
        sizer.Add(self._type_label, 0, wx.LEFT | wx.RIGHT, 8)
        sizer.Add(self._summary, 1, wx.ALL | wx.EXPAND, 8)
        sizer.Add(self._play_button, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(sizer)

        self._current_media: Optional[PlayableMedia] = None

    def update_content(self, obj: Optional[PlexObject], playable: Optional[PlayableMedia]) -> None:
        if obj is None:
            self._title.SetLabel("Select an item to see details.")
            self._type_label.SetLabel("")
            self._summary.SetValue("")
            self._current_media = None
            self._play_button.Disable()
            return

        self._title.SetLabel(getattr(obj, "title", "Untitled"))
        type_label = getattr(obj, "type", "")
        if type_label:
            self._type_label.SetLabel(f"Type: {type_label}")
        else:
            self._type_label.SetLabel("")
        summary = getattr(obj, "summary", "")
        self._summary.SetValue(summary or "")
        self._current_media = playable
        if playable:
            self._play_button.Enable()
        else:
            self._play_button.Disable()

    def _handle_play(self, _: wx.CommandEvent) -> None:
        if self._current_media:
            self._on_play(self._current_media)
