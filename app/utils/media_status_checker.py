# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit
from plexapi.exceptions import NotFound

# On importe tout ce dont on a besoin pour les films ET les séries
from .arr_client import search_radarr_by_title, search_sonarr_by_title, get_sonarr_episode_files
# Remove direct import of get_user_specific_plex_server as it's no longer called directly for shows
# from .plex_client import get_user_specific_plex_server
# For movies, we might still need it, or adapt movies to use a cache too.
# For now, let's keep it if movies logic is untouched regarding direct Plex calls.
from .plex_client import get_user_specific_plex_server


# La fonction accepte maintenant les deux caches
def check_media_status(release_title, plex_show_cache=None, plex_episode_cache=None):
    if plex_show_cache is None: plex_show_cache = {}
    if plex_episode_cache is None: plex_episode_cache = {}

    current_app.logger.info(f"--- Check Status pour: {release_title} (Show Cache: {len(plex_show_cache)}, Episode Cache: {sum(len(v) for v in plex_episode_cache.values())} items) ---")
    """
    Parses a release title using guessit and checks its status in Plex/Sonarr/Radarr.
    Uses pre-loaded caches for Plex show and episode lookups.
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
            # Attempt to get tvdb_id from Sonarr result and convert to int
            try:
                tvdb_id = int(sonarr_series.get('tvdbId'))
            except (ValueError, TypeError):
                current_app.logger.warning(f"Could not parse or invalid TVDB ID from Sonarr for series '{title}': {sonarr_series.get('tvdbId')}")
                # If TVDB ID is missing or invalid from Sonarr, we cannot reliably check Plex.
                # Fallback to Sonarr's monitored status.
                if sonarr_series.get('monitored'):
                    return status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'}) or status_info
                else:
                    return status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'}) or status_info

            # On vérifie si l'épisode est dans notre cache d'épisodes
            # Ensure season_num and episode_num are not None before creating the tuple for lookup
            if season_num is not None and episode_num is not None:
                episode_key = (season_num, episode_num)
                if tvdb_id in plex_episode_cache and episode_key in plex_episode_cache[tvdb_id]:
                    current_app.logger.debug(f"Episode S{season_num:02d}E{episode_num:02d} for TVDB ID {tvdb_id} ('{title}') found in Plex episode cache.")
                    return status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'}) or status_info
                else:
                    current_app.logger.debug(f"Episode S{season_num:02d}E{episode_num:02d} for TVDB ID {tvdb_id} ('{title}') NOT found in Plex episode cache.")
            else:
                current_app.logger.warning(f"Season or episode number missing for '{title}' from guessit. Cannot check Plex episode cache.")

            # Si non présent dans le cache Plex, on se base sur le statut Sonarr
            if sonarr_series.get('monitored'):
                return status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'}) or status_info
            else:
                return status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'}) or status_info

        return status_info

    except Exception as e:
        current_app.logger.error(f"Erreur dans check_media_status pour '{release_title}': {e}", exc_info=True)
        return status_info.update({'status': 'Erreur Analyse', 'badge_color': 'danger'}) or status_info