# app/utils/status_manager.py

from flask import current_app
from app.utils.arr_client import get_sonarr_series_by_guid, get_radarr_movie_by_guid, get_sonarr_episode_files
from app.utils.archive_manager import get_archived_media_by_id

def get_media_statuses(tmdb_id=None, tvdb_id=None, media_type=None):
    """
    Orchestrates the checking of media status across all relevant services.
    Returns a list of status strings.
    """
    statuses = []

    # If we couldn't even identify the media, we can't check its status.
    if not tmdb_id and not tvdb_id:
        return ['UNKNOWN_ID']

    # Check Sonarr/Radarr status
    arr_status = _check_arr_status(tmdb_id, tvdb_id, media_type)
    if arr_status:
        statuses.append(arr_status)

        # If the media is obtained in Arr, it's considered present in Plex
        if arr_status.endswith('_OBTAINED'):
            statuses.append('PLEX_PRESENT')

    # Check archive status
    archive_status = _check_archive_status(tmdb_id, tvdb_id, media_type)
    if archive_status:
        statuses.append(archive_status)

    return statuses

from app.utils.arr_client import get_sonarr_series_by_guid, get_radarr_movie_by_guid, get_sonarr_episode_files

def _check_arr_status(tmdb_id, tvdb_id, media_type):
    """Checks Sonarr or Radarr and returns a detailed status."""
    if media_type == 'tv' and tvdb_id:
        plex_guid = f'tvdb://{tvdb_id}'
        series = get_sonarr_series_by_guid(plex_guid)
        if series:
            # A more reliable way to check if files exist is to query for episode files.
            # An empty list means no files, hence not "obtained".
            episode_files = get_sonarr_episode_files(series.get('id'))
            if episode_files: # The list is not None and not empty
                return 'SONARR_OBTAINED'
            return 'SONARR_MONITORED'

    elif media_type == 'movie' and tmdb_id:
        plex_guid = f'tmdb://{tmdb_id}'
        movie = get_radarr_movie_by_guid(plex_guid)
        if movie:
            if movie.get('hasFile', False):
                return 'RADARR_OBTAINED'
            return 'RADARR_MONITORED'

    return None

def _check_archive_status(tmdb_id, tvdb_id, media_type):
    """Checks if the media is in the Plex archive."""
    archive_id = None
    if media_type == 'tv' and tvdb_id:
        archive_id = f'tv_{tvdb_id}'
    elif media_type == 'movie' and tmdb_id:
        archive_id = f'movie_{tmdb_id}'

    if archive_id and get_archived_media_by_id(archive_id):
        return 'ARCHIVED'

    return None
