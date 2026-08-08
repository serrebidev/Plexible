"""Tests for PlexService methods wrapping the full plexapi surface."""

from unittest.mock import MagicMock, patch

import pytest

from plex_client.plex_service import PlexService


# ============================================================================
# METADATA EDITING
# ============================================================================


class TestMetadataEditing:
    """Test metadata editing methods."""

    def test_edit_item_title(self, plex_service, mock_video):
        plex_service.edit_item_title(mock_video, "New Title")
        mock_video.editTitle.assert_called_once_with("New Title")

    def test_edit_item_summary(self, plex_service, mock_video):
        plex_service.edit_item_summary(mock_video, "New summary")
        mock_video.editSummary.assert_called_once_with("New summary")

    def test_edit_item_sort_title(self, plex_service, mock_video):
        plex_service.edit_item_sort_title(mock_video, "Sort Me")
        mock_video.editSortTitle.assert_called_once_with("Sort Me")

    def test_edit_item_user_rating(self, plex_service, mock_video):
        plex_service.edit_item_user_rating(mock_video, 7.5)
        mock_video.editUserRating.assert_called_once_with(7.5)

    def test_edit_item_audience_rating(self, plex_service, mock_video):
        plex_service.edit_item_audience_rating(mock_video, 8.0)
        mock_video.editAudienceRating.assert_called_once_with(8.0)

    def test_edit_item_critic_rating(self, plex_service, mock_video):
        plex_service.edit_item_critic_rating(mock_video, 9.0)
        mock_video.editCriticRating.assert_called_once_with(9.0)

    def test_edit_item_content_rating(self, plex_service, mock_video):
        plex_service.edit_item_content_rating(mock_video, "PG-13")
        mock_video.editContentRating.assert_called_once_with("PG-13")

    def test_edit_item_originally_available(self, plex_service, mock_video):
        plex_service.edit_item_originally_available(mock_video, "2024-01-01")
        mock_video.editOriginallyAvailable.assert_called_once_with("2024-01-01")

    def test_edit_item_original_title(self, plex_service, mock_video):
        plex_service.edit_item_original_title(mock_video, "Original")
        mock_video.editOriginalTitle.assert_called_once_with("Original")

    def test_edit_item_studio(self, plex_service, mock_video):
        plex_service.edit_item_studio(mock_video, "Test Studio")
        mock_video.editStudio.assert_called_once_with("Test Studio")

    def test_edit_item_tagline(self, plex_service, mock_video):
        plex_service.edit_item_tagline(mock_video, "Best movie ever")
        mock_video.editTagline.assert_called_once_with("Best movie ever")

    def test_edit_item_added_at(self, plex_service, mock_video):
        plex_service.edit_item_added_at(mock_video, "2024-06-15")
        mock_video.editAddedAt.assert_called_once_with("2024-06-15")

    def test_edit_item_tags_add_genre(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_genre=["Action", "Drama"])
        mock_video.addGenre.assert_any_call("Action")
        mock_video.addGenre.assert_any_call("Drama")

    def test_edit_item_tags_remove_genre(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_genre=["Comedy"])
        mock_video.removeGenre.assert_called_once_with("Comedy")

    def test_edit_item_tags_add_collection(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_collection=["Best Of"])
        mock_video.addCollection.assert_called_once_with("Best Of")

    def test_edit_item_tags_remove_collection(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_collection=["Old"])
        mock_video.removeCollection.assert_called_once_with("Old")

    def test_edit_item_tags_add_label(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_label=["Favorites"])
        mock_video.addLabel.assert_called_once_with("Favorites")

    def test_edit_item_tags_remove_label(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_label=["Old"])
        mock_video.removeLabel.assert_called_once_with("Old")

    def test_edit_item_tags_add_mood(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_mood=["Energetic"])
        mock_video.addMood.assert_called_once_with("Energetic")

    def test_edit_item_tags_remove_mood(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_mood=["Sad"])
        mock_video.removeMood.assert_called_once_with("Sad")

    def test_edit_item_tags_add_style(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_style=["Rock"])
        mock_video.addStyle.assert_called_once_with("Rock")

    def test_edit_item_tags_remove_style(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_style=["Pop"])
        mock_video.removeStyle.assert_called_once_with("Pop")

    def test_edit_item_tags_add_country(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_country=["USA"])
        mock_video.addCountry.assert_called_once_with("USA")

    def test_edit_item_tags_remove_country(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_country=["Canada"])
        mock_video.removeCountry.assert_called_once_with("Canada")

    def test_edit_item_tags_add_director(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_director=["Nolan"])
        mock_video.addDirector.assert_called_once_with("Nolan")

    def test_edit_item_tags_remove_director(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_director=["Old"])
        mock_video.removeDirector.assert_called_once_with("Old")

    def test_edit_item_tags_add_writer(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_writer=["Writer One"])
        mock_video.addWriter.assert_called_once_with("Writer One")

    def test_edit_item_tags_remove_writer(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_writer=["Old"])
        mock_video.removeWriter.assert_called_once_with("Old")

    def test_edit_item_tags_add_producer(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_producer=["Producer X"])
        mock_video.addProducer.assert_called_once_with("Producer X")

    def test_edit_item_tags_remove_producer(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_producer=["Old"])
        mock_video.removeProducer.assert_called_once_with("Old")

    def test_edit_item_tags_add_similar_artist(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, add_similar_artist=["Artist"])
        mock_video.addSimilarArtist.assert_called_once_with("Artist")

    def test_edit_item_tags_remove_similar_artist(self, plex_service, mock_video):
        plex_service.edit_item_tags(mock_video, remove_similar_artist=["Old"])
        mock_video.removeSimilarArtist.assert_called_once_with("Old")

    def test_edit_item_tags_raises_when_none_supported(self, plex_service):
        """Raise NotImplementedError when item supports no tag methods."""
        item = MagicMock(spec=[])
        with pytest.raises(NotImplementedError):
            plex_service.edit_item_tags(item, add_genre=["Action"])

    def test_edit_item_not_supported_raises(self, plex_service):
        """An item without editTitle should raise NotImplementedError."""
        item = MagicMock(spec=[])
        with pytest.raises(NotImplementedError, match="editTitle"):
            plex_service.edit_item_title(item, "Test")


# ============================================================================
# MATCH / UNMATCH / SPLIT / MERGE
# ============================================================================


class TestMatchUnmatch:
    """Test match/unmatch methods."""

    def test_get_matches(self, plex_service, mock_video):
        mock_result = MagicMock()
        mock_video.matches.return_value = [mock_result]
        results = plex_service.get_matches(mock_video, "Test Movie")
        assert results == [mock_result]
        mock_video.matches.assert_called_once_with("Test Movie")

    def test_get_matches_with_year_and_agent(self, plex_service, mock_video):
        mock_result = MagicMock()
        mock_video.matches.return_value = [mock_result]
        results = plex_service.get_matches(mock_video, "Test Movie", year="2024", agent="com.plexapp.agents.imdb")
        assert results == [mock_result]
        mock_video.matches.assert_called_once_with("Test Movie", year="2024", agent="com.plexapp.agents.imdb")

    def test_match_item_applies_first_match(self, plex_service, mock_video):
        mock_result = MagicMock()
        mock_video.matches.return_value = [mock_result]
        plex_service.match_item(mock_video, "Test Movie")
        mock_video.fixMatch.assert_called_once_with(mock_result)

    def test_match_item_no_matches_raises(self, plex_service, mock_video):
        mock_video.matches.return_value = []
        with pytest.raises(RuntimeError, match="No matches found"):
            plex_service.match_item(mock_video, "Test Movie")

    def test_unmatch_item(self, plex_service, mock_video):
        plex_service.unmatch_item(mock_video)
        mock_video.unmatch.assert_called_once()

    def test_fix_match(self, plex_service, mock_video):
        match_obj = MagicMock()
        plex_service.fix_match(mock_video, match_obj)
        mock_video.fixMatch.assert_called_once_with(match_obj)

    def test_no_matches_support_raises(self, plex_service):
        item = MagicMock(spec=[])
        with pytest.raises(NotImplementedError, match="matches"):
            plex_service.get_matches(item, "Test")


class TestSplitMerge:
    """Test split/merge methods."""

    def test_split_item(self, plex_service, mock_video):
        plex_service.split_item(mock_video)
        mock_video.split.assert_called_once()

    def test_merge_items(self, plex_service, mock_video):
        other = MagicMock()
        plex_service.merge_items(mock_video, other)
        mock_video.merge.assert_called_once_with(other)

    def test_split_not_supported_raises(self, plex_service):
        item = MagicMock(spec=[])
        with pytest.raises(NotImplementedError, match="split"):
            plex_service.split_item(item)

    def test_merge_not_supported_raises(self, plex_service):
        item = MagicMock(spec=[])
        other = MagicMock()
        with pytest.raises(NotImplementedError, match="merge"):
            plex_service.merge_items(item, other)


# ============================================================================
# ART MANAGEMENT
# ============================================================================


class TestArtManagement:
    """Test art management methods."""

    def test_set_item_art(self, plex_service, mock_video):
        plex_service.set_item_art(mock_video, "http://example.com/art.jpg")
        mock_video.setArt.assert_called_once_with("http://example.com/art.jpg")

    def test_set_item_poster(self, plex_service, mock_video):
        plex_service.set_item_poster(mock_video, "http://example.com/poster.jpg")
        mock_video.setPoster.assert_called_once_with("http://example.com/poster.jpg")

    def test_upload_item_art(self, plex_service, mock_video):
        plex_service.upload_item_art(mock_video, "/path/to/art.jpg")
        mock_video.uploadArt.assert_called_once_with("/path/to/art.jpg")

    def test_upload_item_poster(self, plex_service, mock_video):
        plex_service.upload_item_poster(mock_video, "/path/to/poster.jpg")
        mock_video.uploadPoster.assert_called_once_with("/path/to/poster.jpg")

    def test_lock_item_art(self, plex_service, mock_video):
        plex_service.lock_item_art(mock_video)
        mock_video.lockArt.assert_called_once()

    def test_unlock_item_art(self, plex_service, mock_video):
        plex_service.unlock_item_art(mock_video)
        mock_video.unlockArt.assert_called_once()

    def test_lock_item_poster(self, plex_service, mock_video):
        plex_service.lock_item_poster(mock_video)
        mock_video.lockPoster.assert_called_once()

    def test_unlock_item_poster(self, plex_service, mock_video):
        plex_service.unlock_item_poster(mock_video)
        mock_video.unlockPoster.assert_called_once()

    def test_delete_item_art(self, plex_service, mock_video):
        plex_service.delete_item_art(mock_video)
        mock_video.deleteArt.assert_called_once()

    def test_delete_item_poster(self, plex_service, mock_video):
        plex_service.delete_item_poster(mock_video)
        mock_video.deletePoster.assert_called_once()

    def test_art_method_not_supported_raises(self, plex_service):
        item = MagicMock(spec=[])
        with pytest.raises(NotImplementedError, match="setArt"):
            plex_service.set_item_art(item, "url")


# ============================================================================
# RATE / PLAYED / UNPLAYED
# ============================================================================


class TestRatePlayedUnplayed:
    """Test rate, mark_played, and mark_unplayed methods."""

    def test_rate_item(self, plex_service, mock_video):
        plex_service.rate_item(mock_video, 8.5)
        mock_video.rate.assert_called_once_with(8.5)

    def test_rate_item_not_supported_raises(self, plex_service):
        item = MagicMock(spec=[])
        with pytest.raises(NotImplementedError, match="rating"):
            plex_service.rate_item(item, 5.0)

    def test_mark_played(self, plex_service, mock_video):
        plex_service.mark_played(mock_video)
        mock_video.markPlayed.assert_called_once()

    def test_mark_unplayed(self, plex_service, mock_video):
        plex_service.mark_unplayed(mock_video)
        mock_video.markUnplayed.assert_called_once()

    def test_mark_played_not_supported_raises(self, plex_service):
        item = MagicMock(spec=[])
        with pytest.raises(NotImplementedError, match="markPlayed"):
            plex_service.mark_played(item)

    def test_mark_unplayed_not_supported_raises(self, plex_service):
        item = MagicMock(spec=[])
        with pytest.raises(NotImplementedError, match="markUnplayed"):
            plex_service.mark_unplayed(item)


# ============================================================================
# CLIENT CONTROL
# ============================================================================


class TestClientControl:
    """Test client remote control methods."""

    def test_client_play(self, plex_service):
        plex_service.client_play("test-client")
        client = plex_service._server.client.return_value
        client.play.assert_called_once()

    def test_client_pause(self, plex_service):
        plex_service.client_pause("test-client")
        client = plex_service._server.client.return_value
        client.pause.assert_called_once()

    def test_client_stop(self, plex_service):
        plex_service.client_stop("test-client")
        client = plex_service._server.client.return_value
        client.stop.assert_called_once()

    def test_client_seek_to(self, plex_service):
        plex_service.client_seek_to("test-client", 60000)
        client = plex_service._server.client.return_value
        client.seekTo.assert_called_once_with(60000)

    def test_client_skip_next(self, plex_service):
        plex_service.client_skip_next("test-client")
        client = plex_service._server.client.return_value
        client.skipNext.assert_called_once()

    def test_client_skip_previous(self, plex_service):
        plex_service.client_skip_previous("test-client")
        client = plex_service._server.client.return_value
        client.skipPrevious.assert_called_once()

    def test_client_step_forward(self, plex_service):
        plex_service.client_step_forward("test-client")
        client = plex_service._server.client.return_value
        client.stepForward.assert_called_once()

    def test_client_step_back(self, plex_service):
        plex_service.client_step_back("test-client")
        client = plex_service._server.client.return_value
        client.stepBack.assert_called_once()

    def test_client_set_volume(self, plex_service):
        plex_service.client_set_volume("test-client", 75)
        client = plex_service._server.client.return_value
        client.setVolume.assert_called_once_with(75)

    def test_client_set_audio_stream(self, plex_service):
        plex_service.client_set_audio_stream("test-client", 1)
        client = plex_service._server.client.return_value
        client.setAudioStream.assert_called_once_with(1)

    def test_client_set_subtitle_stream(self, plex_service):
        plex_service.client_set_subtitle_stream("test-client", 2)
        client = plex_service._server.client.return_value
        client.setSubtitleStream.assert_called_once_with(2)

    def test_client_set_video_stream(self, plex_service):
        plex_service.client_set_video_stream("test-client", 0)
        client = plex_service._server.client.return_value
        client.setVideoStream.assert_called_once_with(0)

    def test_client_set_shuffle(self, plex_service):
        plex_service.client_set_shuffle("test-client", True)
        client = plex_service._server.client.return_value
        client.setShuffle.assert_called_once_with(True)

    def test_client_set_repeat(self, plex_service):
        plex_service.client_set_repeat("test-client", True)
        client = plex_service._server.client.return_value
        client.setRepeat.assert_called_once_with(True)

    def test_client_navigate_home(self, plex_service):
        plex_service.client_navigate_home("test-client")
        client = plex_service._server.client.return_value
        client.goToHome.assert_called_once()

    def test_client_navigate_media(self, plex_service):
        plex_service.client_navigate_media("test-client", "/library/metadata/1")
        client = plex_service._server.client.return_value
        client.goToMedia.assert_called_once_with("/library/metadata/1")

    def test_client_navigate_music(self, plex_service):
        plex_service.client_navigate_music("test-client")
        client = plex_service._server.client.return_value
        client.goToMusic.assert_called_once()

    def test_client_move_up(self, plex_service):
        plex_service.client_move_up("test-client")
        client = plex_service._server.client.return_value
        client.moveUp.assert_called_once()

    def test_client_move_down(self, plex_service):
        plex_service.client_move_down("test-client")
        client = plex_service._server.client.return_value
        client.moveDown.assert_called_once()

    def test_client_move_left(self, plex_service):
        plex_service.client_move_left("test-client")
        client = plex_service._server.client.return_value
        client.moveLeft.assert_called_once()

    def test_client_move_right(self, plex_service):
        plex_service.client_move_right("test-client")
        client = plex_service._server.client.return_value
        client.moveRight.assert_called_once()

    def test_client_select(self, plex_service):
        plex_service.client_select("test-client")
        client = plex_service._server.client.return_value
        client.select.assert_called_once()

    def test_client_go_back(self, plex_service):
        plex_service.client_go_back("test-client")
        client = plex_service._server.client.return_value
        client.goBack.assert_called_once()

    def test_client_toggle_osd(self, plex_service):
        plex_service.client_toggle_osd("test-client")
        client = plex_service._server.client.return_value
        client.toggleOSD.assert_called_once()

    def test_client_context_menu(self, plex_service):
        plex_service.client_context_menu("test-client")
        client = plex_service._server.client.return_value
        client.contextMenu.assert_called_once()

    def test_client_page_up(self, plex_service):
        plex_service.client_page_up("test-client")
        client = plex_service._server.client.return_value
        client.pageUp.assert_called_once()

    def test_client_page_down(self, plex_service):
        plex_service.client_page_down("test-client")
        client = plex_service._server.client.return_value
        client.pageDown.assert_called_once()

    def test_client_next_letter(self, plex_service):
        plex_service.client_next_letter("test-client")
        client = plex_service._server.client.return_value
        client.nextLetter.assert_called_once()

    def test_client_previous_letter(self, plex_service):
        plex_service.client_previous_letter("test-client")
        client = plex_service._server.client.return_value
        client.previousLetter.assert_called_once()

    def test_client_play_media(self, plex_service, mock_video):
        plex_service.client_play_media("test-client", mock_video)
        client = plex_service._server.client.return_value
        client.playMedia.assert_called_once_with(mock_video)

    def test_client_is_playing(self, plex_service):
        client = plex_service._server.client.return_value
        client.isPlayingMedia.return_value = True
        assert plex_service.client_is_playing("test-client") is True
        client.isPlayingMedia.return_value = False
        assert plex_service.client_is_playing("test-client") is False


# ============================================================================
# GDM DISCOVERY
# ============================================================================


class TestGDMDiscovery:
    """Test GDM local server discovery."""

    def test_discover_local_servers(self, plex_service):
        mock_gdm = MagicMock()
        mock_gdm.scan.return_value = [
            {
                "data": {
                    "Name": "Living Room Plex",
                    "Host": "192.168.1.50",
                    "Port": "32400",
                    "Client-Identifier": "abc123",
                }
            }
        ]
        with patch("plexapi.gdm.GDM", return_value=mock_gdm):
            servers = plex_service.discover_local_servers(timeout=2)
            assert len(servers) == 1
            assert servers[0]["name"] == "Living Room Plex"
            assert servers[0]["host"] == "192.168.1.50"
            assert servers[0]["port"] == 32400
            assert servers[0]["clientIdentifier"] == "abc123"

    def test_discover_local_servers_empty(self, plex_service):
        mock_gdm = MagicMock()
        mock_gdm.scan.return_value = []
        with patch("plexapi.gdm.GDM", return_value=mock_gdm):
            servers = plex_service.discover_local_servers()
            assert servers == []

    def test_discover_local_servers_no_data_key(self, plex_service):
        mock_gdm = MagicMock()
        mock_gdm.scan.return_value = [
            {
                "host": "192.168.1.60",
                "port": 32400,
                "data": {},
            }
        ]
        with patch("plexapi.gdm.GDM", return_value=mock_gdm):
            servers = plex_service.discover_local_servers()
            assert len(servers) == 1
            assert servers[0]["name"] == "Unknown"
            assert servers[0]["host"] == "192.168.1.60"

    def test_discover_local_servers_resource_identifier(self, plex_service):
        mock_gdm = MagicMock()
        mock_gdm.scan.return_value = [
            {
                "data": {
                    "Name": "Server",
                    "Host": "10.0.0.1",
                    "Port": "32400",
                    "Resource-Identifier": "res123",
                }
            }
        ]
        with patch("plexapi.gdm.GDM", return_value=mock_gdm):
            servers = plex_service.discover_local_servers()
            assert servers[0]["clientIdentifier"] == "res123"

    def test_discover_local_servers_default_port(self, plex_service):
        mock_gdm = MagicMock()
        mock_gdm.scan.return_value = [
            {
                "data": {
                    "Name": "Server",
                    "Host": "10.0.0.1",
                }
            }
        ]
        with patch("plexapi.gdm.GDM", return_value=mock_gdm):
            servers = plex_service.discover_local_servers()
            assert servers[0]["port"] == 32400
