"""Tests for PlexService media management features."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestMediaManagement:
    """Test media item management functionality."""

    def test_remove_from_continue_watching(self, plex_service, mock_video):
        """Test removing item from continue watching."""
        plex_service.remove_from_continue_watching(mock_video)
        
        mock_video.removeFromContinueWatching.assert_called_once()

    def test_remove_from_continue_watching_not_supported(self, plex_service):
        """Test removing item that doesn't support continue watching."""
        item = MagicMock(spec=[])  # No removeFromContinueWatching method
        
        with pytest.raises(NotImplementedError):
            plex_service.remove_from_continue_watching(item)

    def test_mark_watched(self, plex_service, mock_video):
        """Test marking an item as watched."""
        plex_service.mark_watched(mock_video)
        
        mock_video.markWatched.assert_called_once()

    def test_mark_unwatched(self, plex_service, mock_video):
        """Test marking an item as unwatched."""
        plex_service.mark_unwatched(mock_video)
        
        mock_video.markUnwatched.assert_called_once()

    def test_delete_item(self, plex_service, mock_video):
        """Test deleting an item."""
        plex_service.delete_item(mock_video)
        
        mock_video.delete.assert_called_once()

    def test_refresh_item(self, plex_service, mock_video):
        """Test refreshing item metadata."""
        plex_service.refresh_item(mock_video)
        
        mock_video.refresh.assert_called_once()

    def test_analyze_item(self, plex_service, mock_video):
        """Test analyzing an item."""
        plex_service.analyze_item(mock_video)
        
        mock_video.analyze.assert_called_once()


class TestSubtitleManagement:
    """Test subtitle-related functionality."""

    def test_upload_subtitles(self, plex_service, mock_video):
        """Test uploading subtitles."""
        plex_service.upload_subtitles(mock_video, "/path/to/subtitles.srt")
        
        mock_video.uploadSubtitles.assert_called_once_with("/path/to/subtitles.srt")

    def test_search_subtitles(self, plex_service, mock_video):
        """Test searching for subtitles."""
        subtitle = MagicMock()
        subtitle.language = "en"
        mock_video.searchSubtitles.return_value = [subtitle]
        
        results = plex_service.search_subtitles(mock_video, language="en")
        
        assert len(results) == 1
        mock_video.searchSubtitles.assert_called_once_with(
            language="en",
            hearingImpaired=0,
            forced=0,
        )

    def test_search_subtitles_with_options(self, plex_service, mock_video):
        """Test searching for subtitles with options."""
        plex_service.search_subtitles(
            mock_video,
            language="es",
            hearing_impaired=1,
            forced=1,
        )
        
        mock_video.searchSubtitles.assert_called_once_with(
            language="es",
            hearingImpaired=1,
            forced=1,
        )

    def test_search_subtitles_supports_snake_case_hearing_impaired(self, plex_service, mock_video):
        """Map hearingImpaired to hearing_impaired when signatures differ."""
        captured = {}

        def search_subtitles(*, language=None, hearing_impaired=None, forced=None):
            captured["language"] = language
            captured["hearing_impaired"] = hearing_impaired
            captured["forced"] = forced
            return []

        mock_video.searchSubtitles = search_subtitles

        plex_service.search_subtitles(mock_video, language="fr", hearing_impaired=1, forced=0)

        assert captured == {"language": "fr", "hearing_impaired": 1, "forced": 0}

    def test_download_subtitles(self, plex_service, mock_video):
        """Test downloading subtitles."""
        subtitle_stream = MagicMock()
        
        plex_service.download_subtitles(mock_video, subtitle_stream)
        
        mock_video.downloadSubtitles.assert_called_once_with(subtitle_stream)

    def test_remove_subtitles(self, plex_service, mock_video):
        """Test removing subtitles."""
        subtitle_stream = MagicMock()
        
        plex_service.remove_subtitles(mock_video, subtitle_stream=subtitle_stream)
        
        mock_video.removeSubtitles.assert_called_once_with(
            subtitleStream=subtitle_stream,
            streamID=None,
            streamTitle=None,
        )

    def test_remove_subtitles_by_id(self, plex_service, mock_video):
        """Test removing subtitles by stream ID."""
        plex_service.remove_subtitles(mock_video, stream_id=3)
        
        mock_video.removeSubtitles.assert_called_once_with(
            subtitleStream=None,
            streamID=3,
            streamTitle=None,
        )

    def test_remove_subtitles_supports_snake_case_aliases(self, plex_service, mock_video):
        """Map removeSubtitles camelCase kwargs to snake_case variants."""
        subtitle_stream = MagicMock()
        captured = {}

        def remove_subtitles(*, subtitle_stream=None, stream_id=None, stream_title=None):
            captured["subtitle_stream"] = subtitle_stream
            captured["stream_id"] = stream_id
            captured["stream_title"] = stream_title

        mock_video.removeSubtitles = remove_subtitles

        plex_service.remove_subtitles(
            mock_video,
            subtitle_stream=subtitle_stream,
            stream_id=7,
            stream_title="English SDH",
        )

        assert captured == {
            "subtitle_stream": subtitle_stream,
            "stream_id": 7,
            "stream_title": "English SDH",
        }


class TestOptimization:
    """Test media optimization functionality."""

    def test_optimize_item(self, plex_service, mock_video):
        """Test creating optimized version."""
        plex_service.optimize_item(
            mock_video,
            title="Mobile Version",
            target="mobile",
            video_quality=8,
        )
        
        mock_video.optimize.assert_called_once()

    def test_optimize_item_supports_snake_case_aliases(self, plex_service, mock_video):
        """Map optimize camelCase kwargs to snake_case variants."""
        captured = {}

        def optimize(*, title=None, target=None, device_profile=None, video_quality=None):
            captured["title"] = title
            captured["target"] = target
            captured["device_profile"] = device_profile
            captured["video_quality"] = video_quality

        mock_video.optimize = optimize

        plex_service.optimize_item(
            mock_video,
            title="Tablet",
            target="mobile",
            device_profile="android",
            video_quality=6,
        )

        assert captured == {
            "title": "Tablet",
            "target": "mobile",
            "device_profile": "android",
            "video_quality": 6,
        }

    def test_optimize_item_not_supported(self, plex_service):
        """Test optimizing item that doesn't support it."""
        item = MagicMock(spec=[])  # No optimize method
        
        with pytest.raises(NotImplementedError):
            plex_service.optimize_item(item)


class TestDownload:
    """Test download functionality."""

    def test_download_item(self, plex_service, mock_video):
        """Test downloading an item."""
        result = plex_service.download_item(mock_video, savepath="/downloads")
        
        assert "/path/to/file.mp4" in result
        mock_video.download.assert_called_once()

    def test_download_item_supports_camel_case_keep_original_name(self, plex_service, mock_video):
        """Map download keep_original_name to keepOriginalName signatures."""
        captured = {}

        def download(*, savePath=None, keepOriginalName=None):
            captured["savePath"] = savePath
            captured["keepOriginalName"] = keepOriginalName
            return ["/tmp/test.mp4"]

        mock_video.download = download

        result = plex_service.download_item(mock_video, savepath="/downloads", keep_original_name=True)

        assert result == ["/tmp/test.mp4"]
        assert captured == {"savePath": "/downloads", "keepOriginalName": True}

    def test_download_item_not_supported(self, plex_service):
        """Test downloading item that doesn't support it."""
        item = MagicMock(spec=[])  # No download method
        
        with pytest.raises(NotImplementedError):
            plex_service.download_item(item)

    def test_download_databases(self, plex_service, mock_server):
        """Test downloading server databases."""
        result = plex_service.download_databases(savepath="/backups")
        
        assert result == "/path/to/db.zip"
        mock_server.downloadDatabases.assert_called_once()

    def test_download_logs(self, plex_service, mock_server):
        """Test downloading server logs."""
        result = plex_service.download_logs(savepath="/logs")
        
        assert result == "/path/to/logs.zip"
        mock_server.downloadLogs.assert_called_once()
