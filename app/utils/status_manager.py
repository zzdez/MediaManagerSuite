
from flask import current_app

# Import clients for Sonarr, Radarr, TMDB, and Plex
from app.utils.arr_client import get_sonarr_series_by_guid, get_radarr_movie_by_guid
from app.utils.tmdb_client import TheMovieDBClient
from app.utils.plex_client import find_plex_media_by_guid_global
from app.utils.archive_manager import find_archived_media_by_id as get_archived_media_by_id

# Import mapping manager to check for seedbox status
from app.utils import mapping_manager

def get_media_statuses(tmdb_id, media_type):
    """
    Orchestrator function to get all statuses for a given media item.

    :param tmdb_id: The Movie DB ID of the media.
    :param media_type: 'movie' or 'tv'.
    :return: A list of status strings.
    """
    if not tmdb_id:
        return ["ID Manquant"]

    statuses = []
    tvdb_id = None

    # For TV shows, we need the TVDB ID. This logic is now centralized here.
    if media_type == 'tv':
        try:
            tmdb_client = TheMovieDBClient()
            details = tmdb_client.get_series_details(tmdb_id)
            if details:
                tvdb_id = details.get('tvdb_id')
        except Exception as e:
            current_app.logger.error(f"Failed to get TVDB ID for TMDB ID {tmdb_id}: {e}")
            # We can continue without it, Sonarr check will just be skipped.

    # Check statuses from all services
    statuses.extend(_check_radarr_status(tmdb_id, media_type))
    statuses.extend(_check_sonarr_status(tvdb_id, media_type))
    statuses.extend(_check_archive_status(tmdb_id, tvdb_id, media_type))
    statuses.extend(_check_seedbox_status(tmdb_id, tvdb_id, media_type))
    statuses.extend(_check_plex_status(tmdb_id, tvdb_id, media_type))

    return statuses

def _check_radarr_status(tmdb_id, media_type):
    """Checks Radarr for movie status."""
    if media_type != 'movie':
        return []

    try:
        radarr_guid = f"tmdb://{tmdb_id}"
        radarr_movie = get_radarr_movie_by_guid(radarr_guid)
        if radarr_movie:
            if radarr_movie.get('hasFile', False):
                return ["Radarr (Obtenu)"]
            elif radarr_movie.get('monitored', False):
                return ["Radarr (Surveillé)"]
    except Exception as e:
        current_app.logger.error(f"Error checking Radarr status for tmdbId {tmdb_id}: {e}")
    return []

def _check_sonarr_status(tvdb_id, media_type):
    """Checks Sonarr for series status."""
    if media_type != 'tv' or not tvdb_id:
        return []

    try:
        sonarr_guid = f"tvdb://{tvdb_id}"
        sonarr_series = get_sonarr_series_by_guid(sonarr_guid)
        if sonarr_series:
            # Check if all episodes are present
            stats = sonarr_series.get('statistics', {})
            if stats.get('percentOfEpisodes', 0) == 100:
                return ["Sonarr (Obtenu)"]
            elif sonarr_series.get('monitored', False):
                return ["Sonarr (Surveillé)"]
    except Exception as e:
        current_app.logger.error(f"Error checking Sonarr status for tvdbId {tvdb_id}: {e}")
    return []

def _check_archive_status(tmdb_id, tvdb_id, media_type):
    """Checks if the media is in the archive_database.json."""
    try:
        if media_type == 'movie':
            if get_archived_media_by_id('movie', tmdb_id):
                return ["Plex (Archivé)"]
        elif media_type == 'tv' and tvdb_id:
            # The archive uses 'show' as media_type for TV series
            if get_archived_media_by_id('show', tvdb_id):
                return ["Plex (Archivé)"]
    except Exception as e:
        current_app.logger.error(f"Error checking archive status for {media_type} id {tmdb_id or tvdb_id}: {e}")
    return []

def _check_plex_status(tmdb_id, tvdb_id, media_type):
    """Checks if the media is currently in the Plex library."""
    guid = None
    if media_type == 'movie' and tmdb_id:
        guid = f"tmdb://{tmdb_id}"
    elif media_type == 'tv' and tvdb_id:
        guid = f"tvdb://{tvdb_id}"

    if guid:
        try:
            media_item = find_plex_media_by_guid_global(guid)
            if media_item:
                return ["Plex (Présent)"]
        except Exception as e:
            current_app.logger.error(f"Error checking Plex status for guid {guid}: {e}")

    return []

def _check_seedbox_status(tmdb_id, tvdb_id, media_type):
    """Checks if a torrent associated with this media is tracked in the mapping_manager."""
    try:
        all_associations = mapping_manager.get_all_torrents_in_map()
        if not all_associations:
            return []

        # Determine the target ID and app_type we are looking for
        target_id = None
        app_type = None
        if media_type == 'movie':
            target_id = tmdb_id
            app_type = 'radarr'
        elif media_type == 'tv' and tvdb_id:
            target_id = tvdb_id
            app_type = 'sonarr'

        if not target_id:
            return []

        # The target_id in the map can be a string or an int, so we compare loosely
        for torrent_hash, data in all_associations.items():
            if data.get('app_type') == app_type and str(data.get('target_id')) == str(target_id):
                # Found a match. The status 'pending_download' indicates it's on the seedbox.
                # Other statuses like 'in_staging' also mean it was on the seedbox.
                # We can consider any tracked torrent as "on the seedbox" for this badge's purpose.
                return ["Seedbox"]

    except Exception as e:
        current_app.logger.error(f"Error checking seedbox status via mapping_manager: {e}")

    return []
