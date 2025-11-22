# app/utils/status_manager.py

from flask import current_app
from app.utils.arr_client import get_radarr_movie_by_guid, parse_media_name, get_sonarr_series_details_by_tvdbid
from app.utils.archive_manager import get_archived_media_by_id

def get_media_statuses(title=None, tmdb_id=None, tvdb_id=None, media_type=None):
    """
    Orchestrates checking media status across all services and returns a structured object.
    """
    statuses = {
        "sonarr": None,
        "radarr": None,
        "plex": None,
        "archive": None,
        "summary": "UNKNOWN" # Default status
    }

    if not tmdb_id and not tvdb_id:
        return statuses

    # --- Check Sonarr/Radarr Status ---
    if media_type == 'tv' and tvdb_id:
        statuses['sonarr'] = _check_sonarr_status(title, tvdb_id)
    elif media_type == 'movie' and tmdb_id:
        statuses['radarr'] = _check_radarr_status(tmdb_id)

    # --- Check Archive Status ---
    archive_status = _check_archive_status(tmdb_id, tvdb_id, media_type)
    if archive_status:
        statuses['archive'] = {"status": "ARCHIVED"}

    # --- Determine Plex and Summary Status ---
    sonarr_status = statuses.get('sonarr')
    radarr_status = statuses.get('radarr')

    if (sonarr_status and sonarr_status.get('episode_status') == 'OBTAINED') or \
       (sonarr_status and sonarr_status.get('season_status', {}).get('is_complete')) or \
       (radarr_status and radarr_status.get('status') == 'OBTAINED'):
        statuses['plex'] = {"status": "PRESENT"}
        statuses['summary'] = "OBTAINED"
    elif sonarr_status or radarr_status:
        statuses['summary'] = "MONITORED"
    elif statuses['archive']:
        statuses['summary'] = "ARCHIVED"
    else:
        statuses['summary'] = "NOT_MANAGED"

    return statuses

def _check_sonarr_status(release_title, tvdb_id):
    """
    Checks Sonarr for a series and calculates detailed status for episode, season, and series.
    Returns a structured dictionary or None.
    """
    series_details = get_sonarr_series_details_by_tvdbid(tvdb_id)
    if not series_details:
        return None

    parsed_info = parse_media_name(release_title)
    season_number_from_release = parsed_info.get('season')
    episode_number_from_release = parsed_info.get('episode')

    all_episodes = series_details.get('episodes', [])

    # --- Calculate Episode Status (if applicable) ---
    episode_status = "NOT_APPLICABLE"
    if episode_number_from_release and season_number_from_release:
        episode_status = "MISSING"
        for ep in all_episodes:
            if ep.get('seasonNumber') == season_number_from_release and ep.get('episodeNumber') == episode_number_from_release and ep.get('hasFile'):
                episode_status = "OBTAINED"
                break

    # --- Calculate Season Status (if a season is in the release title) ---
    season_stats = None
    if season_number_from_release:
        season_episodes = [ep for ep in all_episodes if ep.get('seasonNumber') == season_number_from_release and ep.get('episodeNumber', 0) > 0]
        if season_episodes:
            files_count = sum(1 for ep in season_episodes if ep.get('hasFile'))
            total_episodes = len(season_episodes)
            season_stats = {
                "season_number": season_number_from_release,
                "files_count": files_count,
                "total_episodes": total_episodes,
                "is_complete": files_count >= total_episodes
            }

    # --- Calculate Overall Series Status ---
    total_seasons_count = series_details.get('seasonCount', 0)
    complete_seasons_count = 0
    # Group episodes by season
    seasons_map = {}
    for ep in all_episodes:
        if ep.get('episodeNumber', 0) > 0: # Exclude specials
            s_num = ep.get('seasonNumber')
            if s_num not in seasons_map:
                seasons_map[s_num] = {'total': 0, 'files': 0}
            seasons_map[s_num]['total'] += 1
            if ep.get('hasFile'):
                seasons_map[s_num]['files'] += 1

    for s_num, counts in seasons_map.items():
        if counts['total'] > 0 and counts['files'] >= counts['total']:
            complete_seasons_count += 1

    return {
        "status": "MONITORED",
        "episode_status": episode_status,
        "season_status": season_stats,
        "series_status": {
            "complete_seasons": complete_seasons_count,
            "total_seasons": total_seasons_count
        }
    }

def _check_radarr_status(tmdb_id):
    """Checks Radarr and returns a simple status dictionary."""
    plex_guid = f'tmdb://{tmdb_id}'
    movie = get_radarr_movie_by_guid(plex_guid)
    if movie:
        status = "OBTAINED" if movie.get('hasFile', False) else "MONITORED"
        return {"status": status}
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
