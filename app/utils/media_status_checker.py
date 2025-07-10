# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit # Ensure guessit is imported
from plexapi.exceptions import NotFound

from .arr_client import search_radarr_by_title, search_sonarr_by_title
from .plex_client import get_user_specific_plex_server

def _check_arr_status(parsed_info, status_info_ref, release_title_for_log):
    """Helper function to check Sonarr/Radarr status."""
    media_type = parsed_info.get('type')
    # Use parsed_title from parsed_info for Arr search, as it's cleaner
    arr_search_title = parsed_info.get('title')

    if not arr_search_title: # Should have been caught earlier, but defensive
        current_app.logger.warn(f"_check_arr_status: No title from guessit for '{release_title_for_log}', cannot check Arr.")
        status_info_ref.update({'status': 'Erreur Analyse Titre Arr', 'badge_color': 'danger'})
        return status_info_ref

    current_app.logger.debug(f"_check_arr_status: Checking Arr for '{arr_search_title}' (type: {media_type}) from release '{release_title_for_log}'")

    if media_type == 'movie':
        year = parsed_info.get('year') # Use parsed year for Radarr search
        # status_info_ref['details'] would have been set by the main function if it's a movie

        radarr_results = search_radarr_by_title(arr_search_title)
        found_in_radarr = None
        if radarr_results:
            if year:
                found_in_radarr = next((m for m in radarr_results if m.get('year') == year and m.get('title', '').lower() == arr_search_title.lower()), None)
            if not found_in_radarr: # Fallback if year match fails or no year
                found_in_radarr = next((m for m in radarr_results if m.get('title', '').lower() == arr_search_title.lower()), None)

        if not found_in_radarr:
            status_info_ref.update({'status': 'Non Trouvé (Radarr)', 'badge_color': 'dark'})
        elif found_in_radarr.get('monitored'):
            status_info_ref.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
        else:
            status_info_ref.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})
        return status_info_ref

    elif media_type == 'episode':
        season_num = parsed_info.get('season')
        # episode_num = parsed_info.get('episode') # Not directly used for series search/status
        # status_info_ref['details'] would have been set by the main function for episode

        if not isinstance(season_num, int): # Episode number check is not critical for series monitoring status
            current_app.logger.warn(f"_check_arr_status: Cannot accurately check Sonarr for '{release_title_for_log}' due to missing season number.")
            status_info_ref.update({'status': 'Erreur Analyse Saison (Arr)', 'badge_color': 'danger'})
            return status_info_ref

        sonarr_results = search_sonarr_by_title(arr_search_title) # arr_search_title is series title
        if not sonarr_results:
            status_info_ref.update({'status': 'Série non trouvée', 'badge_color': 'dark'})
            return status_info_ref

        sonarr_series = next((s for s in sonarr_results if s.get('title','').lower() == arr_search_title.lower()), sonarr_results[0])

        if sonarr_series.get('monitored'):
            status_info_ref.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
        else:
            status_info_ref.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})
        return status_info_ref

    # If media_type is unknown or not movie/episode
    current_app.logger.warn(f"_check_arr_status: Type de média inconnu '{media_type}' pour '{release_title_for_log}'. Statut Arr non déterminé.")
    # status_info_ref remains 'Indéterminé' or previous state
    return status_info_ref


def check_media_status(release_title):
    status_info = {
        'status': 'Indéterminé', 
        'details': release_title, # Default details to raw title
        'badge_color': 'secondary',
        'parsed_title': None, # Will be updated by guessit
        'media_type': None    # Will be updated by guessit
    }
    
    try:
        parsed_info = guessit(release_title)
        parsed_title = parsed_info.get('title')
        parsed_year = parsed_info.get('year')
        parsed_season = parsed_info.get('season')
        parsed_episode = parsed_info.get('episode')
        media_type = parsed_info.get('type')

        status_info['media_type'] = media_type
        status_info['parsed_title'] = parsed_title # Store the parsed title

        # Update details string based on parsed info for better display later
        if media_type == 'movie' and parsed_title:
            status_info['details'] = f"{parsed_title} ({parsed_year})" if parsed_year else parsed_title
        elif media_type == 'episode' and parsed_title and isinstance(parsed_season, int) and isinstance(parsed_episode, int):
            status_info['details'] = f"{parsed_title} - S{parsed_season:02d}E{parsed_episode:02d}"
        # else, details remains release_title or as updated by specific logic

        if not parsed_title:
            current_app.logger.warn(f"check_media_status: Guessit failed to find a title for '{release_title}'. Proceeding to Arr check with raw title if possible.")
            # No proper title, Plex check is unlikely to succeed. Fallback to Arr check.
            return _check_arr_status(parsed_info, status_info, release_title)


        # --- ÉTAPE 1: Vérification Plex (Live Query using parsed info) ---
        user_plex = None
        try:
            user_plex = get_user_specific_plex_server()
        except Exception as e:
            current_app.logger.error(f"check_media_status: Erreur lors de la récupération du serveur Plex: {e}", exc_info=True)

        if user_plex:
            current_app.logger.debug(f"check_media_status: Vérification Plex pour '{parsed_title}' (type: {media_type})")
            if media_type == 'movie':
                try:
                    plex_results = user_plex.library.search(title=parsed_title, year=parsed_year, libtype='movie', limit=5)
                    for movie_item in plex_results:
                        # Stricter matching: compare lowercase titles and ensure year matches if provided
                        if movie_item.title.lower() == parsed_title.lower() and \
                           (not parsed_year or movie_item.year == parsed_year):
                            if hasattr(movie_item, 'media') and movie_item.media and \
                               hasattr(movie_item.media[0], 'parts') and movie_item.media[0].parts:
                                current_app.logger.info(f"check_media_status: Film '{parsed_title}' ({parsed_year}) trouvé dans Plex.")
                                status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                                return status_info
                except Exception as e:
                    current_app.logger.error(f"check_media_status: Erreur lors de la recherche du film Plex '{parsed_title}': {e}", exc_info=True)

            elif media_type == 'episode':
                if not all([isinstance(parsed_season, int), isinstance(parsed_episode, int)]):
                    current_app.logger.warn(f"check_media_status: Saison/épisode non parsé correctement pour '{release_title}', Plex check pour épisode ignoré.")
                else:
                    try:
                        plex_shows = user_plex.library.search(title=parsed_title, libtype='show', limit=5) # parsed_title is show title
                        if plex_shows:
                            for show_item in plex_shows:
                                if show_item.title.lower() == parsed_title.lower(): # Match show title
                                    try:
                                        episode_item = show_item.episode(season=parsed_season, episode=parsed_episode)
                                        if episode_item and hasattr(episode_item, 'media') and episode_item.media and \
                                           hasattr(episode_item.media[0], 'parts') and episode_item.media[0].parts:
                                            current_app.logger.info(f"check_media_status: Épisode '{status_info['details']}' trouvé dans Plex.")
                                            status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                                            return status_info
                                    except NotFound:
                                        continue
                                    except Exception as e_ep:
                                        current_app.logger.error(f"check_media_status: Erreur récupération épisode Plex pour '{parsed_title} S{parsed_season}E{parsed_episode}': {e_ep}", exc_info=True)
                                        break
                            current_app.logger.debug(f"check_media_status: Épisode '{status_info['details']}' non trouvé dans Plex.")
                        else:
                            current_app.logger.debug(f"check_media_status: Série '{parsed_title}' non trouvée dans Plex.")
                    except Exception as e_show:
                        current_app.logger.error(f"check_media_status: Erreur recherche série Plex '{parsed_title}': {e_show}", exc_info=True)
        else:
            current_app.logger.warn("check_media_status: user_plex non disponible, Plex check ignoré.")

        # --- ÉTAPE 2: Si non présent dans Plex, vérifier Sonarr/Radarr ---
        return _check_arr_status(parsed_info, status_info, release_title)

    except Exception as e:
        current_app.logger.error(f"Erreur majeure dans check_media_status pour '{release_title}': {e}", exc_info=True)
        status_info.update({'status': 'Erreur Analyse Globale', 'badge_color': 'danger'})
        return status_info