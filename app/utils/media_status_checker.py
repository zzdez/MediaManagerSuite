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


# La fonction accepte maintenant le cache en paramètre
def check_media_status(release_title, plex_show_cache=None):
    if plex_show_cache is None:
        plex_show_cache = {}
    current_app.logger.info(f"--- Check Status pour: {release_title} (Cache: {len(plex_show_cache)} items) ---")
    """
    Parses a release title using guessit and checks its status in Plex/Sonarr/Radarr.
    Uses a pre-loaded cache for Plex show lookups.
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
            tvdb_id_sonarr = sonarr_series.get('tvdbId') # Renamed to avoid clash if we parse tvdb_id from release_title

            # Ensure tvdb_id_sonarr is an integer for cache lookup
            if tvdb_id_sonarr:
                try:
                    tvdb_id_lookup = int(tvdb_id_sonarr)
                except ValueError:
                    current_app.logger.warning(f"Invalid TVDB ID from Sonarr: {tvdb_id_sonarr} for {title}")
                    tvdb_id_lookup = None
            else:
                tvdb_id_lookup = None

            # On utilise le CACHE au lieu de faire une nouvelle recherche Plex !
            plex_series = plex_show_cache.get(tvdb_id_lookup) if tvdb_id_lookup else None

            if plex_series:
                current_app.logger.debug(f"Found '{plex_series.title}' in Plex cache for TVDB ID {tvdb_id_lookup}.")
                try:
                    # Check if the specific episode exists
                    plex_series.episode(season=season_num, episode=episode_num)
                    current_app.logger.debug(f"Episode S{season_num:02d}E{episode_num:02d} for '{plex_series.title}' found in Plex.")
                    return status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'}) or status_info
                except NotFound:
                    current_app.logger.debug(f"Episode S{season_num:02d}E{episode_num:02d} for '{plex_series.title}' NOT found in Plex (show was in cache).")
                    pass # L'épisode n'est pas dans Plex, on continue la logique ci-dessous
            elif tvdb_id_lookup:
                current_app.logger.debug(f"Show with TVDB ID {tvdb_id_lookup} ('{title}') not found in Plex cache.")


            if sonarr_series.get('monitored'):
                return status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'}) or status_info
            else:
                return status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'}) or status_info

        return status_info

    except Exception as e:
        current_app.logger.error(f"Erreur dans check_media_status pour '{release_title}': {e}", exc_info=True)
        return status_info.update({'status': 'Erreur Analyse', 'badge_color': 'danger'}) or status_info