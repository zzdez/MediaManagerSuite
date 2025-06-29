# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit
from plexapi.exceptions import NotFound

# On importe tout ce dont on a besoin pour les films ET les séries
from .arr_client import search_radarr_by_title, search_sonarr_by_title, get_sonarr_episode_files
from .plex_client import get_user_specific_plex_server # Correction de la dépendance circulaire

def check_media_status(release_title):
    """
    Parses a release title using guessit and checks its status in Plex/Sonarr/Radarr.
    """
    status_info = {'status': 'Indéterminé', 'details': release_title, 'badge_color': 'secondary'}
    
    try:
        parsed_info = guessit(release_title)
        title = parsed_info.get('title')
        year = parsed_info.get('year')
        media_type = parsed_info.get('type')

        # --- LOGIQUE POUR LES FILMS (INCHANGÉE, CAR ELLE FONCTIONNE) ---
        if media_type == 'movie':
            status_info['details'] = f"{title} ({year})" if year else title
            radarr_results = search_radarr_by_title(title)
            found_in_radarr = next((m for m in radarr_results if m.get('year') == year), None) if radarr_results else None
            
            if not found_in_radarr or not found_in_radarr.get('tmdbId'):
                return status_info.update({'status': 'Non Trouvé (Radarr)', 'badge_color': 'dark'}) or status_info
            
            user_plex_server = get_user_specific_plex_server()
            if user_plex_server:
                movie_libraries = [lib for lib in user_plex_server.library.sections() if lib.type == 'movie']
                found_in_plex = False
                for library in movie_libraries:
                    if library.search(guid=f"tmdb://{found_in_radarr['tmdbId']}") or library.search(title=title, year=year):
                        found_in_plex = True
                        break
                if found_in_plex:
                    return status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'}) or status_info

            if found_in_radarr.get('hasFile'):
                return status_info.update({'status': 'Statut Inconnu', 'badge_color': 'danger'}) or status_info
            elif found_in_radarr.get('monitored'):
                return status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'}) or status_info
            else:
                return status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'}) or status_info

        # --- NOUVELLE LOGIQUE POUR LES SÉRIES ---
        elif media_type == 'episode':
            season_num = parsed_info.get('season')
            episode_num = parsed_info.get('episode')
            
            if not all([title, season_num, episode_num]):
                return status_info # Informations insuffisantes pour une recherche de série

            status_info['details'] = f"{title} - S{season_num:02d}E{episode_num:02d}"

            sonarr_results = search_sonarr_by_title(title)
            if not sonarr_results:
                return status_info.update({'status': 'Série non trouvée', 'badge_color': 'dark'}) or status_info

            sonarr_series = sonarr_results[0]
            tvdb_id = sonarr_series.get('tvdbId')

            user_plex = get_user_specific_plex_server()
            if user_plex and tvdb_id:
                plex_series = next((s for lib in user_plex.library.sections() if lib.type == 'show' for s in lib.search(guid=f"tvdb://{tvdb_id}")), None)
                if plex_series:
                    try:
                        plex_series.episode(season=season_num, episode=episode_num)
                        return status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'}) or status_info
                    except NotFound:
                        pass # L'épisode n'est pas dans Plex, on continue la logique ci-dessous

            if sonarr_series.get('monitored'):
                return status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'}) or status_info
            else:
                return status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'}) or status_info

        return status_info

    except Exception as e:
        current_app.logger.error(f"Erreur dans check_media_status pour '{release_title}': {e}", exc_info=True)
        return status_info.update({'status': 'Erreur Analyse', 'badge_color': 'danger'}) or status_info