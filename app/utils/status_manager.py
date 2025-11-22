# app/utils/status_manager.py

from flask import current_app
from app.utils.arr_client import get_sonarr_series_by_guid, get_radarr_movie_by_guid, check_sonarr_episode_exists, parse_media_name, get_sonarr_episodes_by_series_id
from app.utils.archive_manager import get_archived_media_by_id

def get_media_statuses(title=None, tmdb_id=None, tvdb_id=None, media_type=None):
    """
    Orchestrates the checking of media status across all relevant services.
    Returns a list of status strings.
    """
    statuses = []

    # If we couldn't even identify the media, we can't check its status.
    if not tmdb_id and not tvdb_id:
        return ['UNKNOWN_ID']

    # Check Sonarr/Radarr status
    arr_statuses = _check_arr_status(title, tmdb_id, tvdb_id, media_type)
    statuses.extend(arr_statuses)

    # If the media is obtained in Arr, it's considered present in Plex
    if 'SONARR_OBTAINED' in statuses or 'RADARR_OBTAINED' in statuses:
        statuses.append('PLEX_PRESENT')

    # Check archive status
    archive_status = _check_archive_status(tmdb_id, tvdb_id, media_type)
    if archive_status:
        statuses.append(archive_status)

    # If, after all checks, no status was found, it means the media is identified but not managed.
    if not statuses:
        statuses.append('NOT_MANAGED')

    return statuses

def _check_arr_status(title, tmdb_id, tvdb_id, media_type):
    """Checks Sonarr or Radarr and returns a list of detailed statuses."""
    statuses = []
    if media_type == 'tv' and tvdb_id:
        plex_guid = f'tvdb://{tvdb_id}'
        series = get_sonarr_series_by_guid(plex_guid)
        if series:
            statuses.append('SONARR_MONITORED')

            # Now, check for the specific episode/season
            parsed_info = parse_media_name(title)
            season_number = parsed_info.get('season')
            episode_number = parsed_info.get('episode')

            if season_number is not None:
                series_title = series.get('title')
                # Si c'est un pack de saison (pas d'épisode), on utilise la nouvelle logique
                if episode_number is None:
                    series_id = series.get('id')
                    all_episodes = get_sonarr_episodes_by_series_id(series_id)
                    if all_episodes:
                        season_episodes = [ep for ep in all_episodes if ep.get('seasonNumber') == season_number]

                        # Compter uniquement les épisodes qui ne sont PAS des "spéciaux" (souvent non numérotés)
                        relevant_episodes = [ep for ep in season_episodes if ep.get('episodeNumber', 0) > 0]

                        if relevant_episodes: # S'il y a des épisodes numérotés dans la saison
                            files_count = sum(1 for ep in relevant_episodes if ep.get('hasFile', False))

                            # Si tous les épisodes pertinents ont un fichier, la saison est "obtenue"
                            if files_count >= len(relevant_episodes):
                                statuses.append('SONARR_OBTAINED')

                # Sinon, on utilise l'ancienne logique pour les épisodes individuels
                else:
                    if check_sonarr_episode_exists(series_title, season_number, episode_number):
                        statuses.append('SONARR_OBTAINED')

    elif media_type == 'movie' and tmdb_id:
        plex_guid = f'tmdb://{tmdb_id}'
        movie = get_radarr_movie_by_guid(plex_guid)
        if movie:
            statuses.append('RADARR_MONITORED')
            if movie.get('hasFile', False):
                statuses.append('RADARR_OBTAINED')

    return statuses

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
