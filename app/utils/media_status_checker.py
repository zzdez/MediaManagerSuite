# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit
from plexapi.exceptions import NotFound

from .arr_client import search_radarr_by_title, search_sonarr_by_title
from .plex_client import get_user_specific_plex_server

def check_media_status(release_title, plex_show_cache=None, plex_episode_cache=None, plex_movie_cache=None):
    if plex_show_cache is None: plex_show_cache = {}
    if plex_episode_cache is None: plex_episode_cache = {}
    if plex_movie_cache is None: plex_movie_cache = {}

    status_info = {
        'status': 'Indéterminé', 
        'details': release_title, 
        'badge_color': 'secondary',
        'parsed_title': None,
        'media_type': None
    }
    
    try:
        parsed_info = guessit(release_title)
        media_type = parsed_info.get('type')
        title = parsed_info.get('title')

        # On enrichit status_info tout de suite
        status_info['media_type'] = media_type
        status_info['parsed_title'] = title

        if not title:
            return status_info # Pas de titre trouvé, on arrête

        # --- LOGIQUE POUR LES FILMS ---
        if media_type == 'movie':
            year = parsed_info.get('year')
            status_info['details'] = f"{title} ({year})" if year else title
            
            tmdb_id_from_plex = next((tmdb_id for tmdb_id, movie_data in plex_movie_cache.items() if movie_data['title'].lower() == title.lower() and movie_data['year'] == year), None)
            
            if tmdb_id_from_plex:
                status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                return status_info

            radarr_results = search_radarr_by_title(title)
            found_in_radarr = next((m for m in radarr_results if m.get('year') == year), None) if radarr_results else None
            
            if not found_in_radarr:
                status_info.update({'status': 'Non Trouvé (Radarr)', 'badge_color': 'dark'})
                return status_info

            if found_in_radarr.get('monitored'):
                status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
            else:
                status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})
            return status_info

        # --- LOGIQUE POUR LES SÉRIES ---
        elif media_type == 'episode':
            season_num = parsed_info.get('season')
            episode_num = parsed_info.get('episode')
            
            if not all([isinstance(season_num, int), isinstance(episode_num, int)]):
                return status_info

            status_info['details'] = f"{title} - S{season_num:02d}E{episode_num:02d}"

            sonarr_results = search_sonarr_by_title(title)
            if not sonarr_results:
                status_info.update({'status': 'Série non trouvée', 'badge_color': 'dark'})
                return status_info
            
            sonarr_series = sonarr_results[0]
            tvdb_id = sonarr_series.get('tvdbId')

            if tvdb_id and tvdb_id in plex_episode_cache and (season_num, episode_num) in plex_episode_cache[tvdb_id]:
                status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                return status_info

            if sonarr_series.get('monitored'):
                status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
            else:
                status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})
            return status_info

        return status_info

    except Exception as e:
        current_app.logger.error(f"Erreur dans check_media_status pour '{release_title}': {e}", exc_info=True)
        status_info.update({'status': 'Erreur Analyse', 'badge_color': 'danger'})
        return status_info