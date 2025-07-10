# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit
from plexapi.exceptions import NotFound

from .arr_client import search_radarr_by_title, search_sonarr_by_title
from .plex_client import get_user_specific_plex_server # Ensure this is correctly imported

# Removed plex_show_cache, plex_episode_cache, plex_movie_cache from parameters as they are no longer used
def check_media_status(release_title):
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
        title = parsed_info.get('title') # This is the series title for episodes, or movie title

        status_info['media_type'] = media_type
        status_info['parsed_title'] = title

        if not title:
            current_app.logger.warn(f"check_media_status: Guessit failed to find a title for '{release_title}'.")
            return status_info

        # --- ÉTAPE 1: Vérification Plex (Live Query) ---
        user_plex = None
        try:
            user_plex = get_user_specific_plex_server()
        except Exception as e:
            current_app.logger.error(f"check_media_status: Erreur lors de la récupération du serveur Plex: {e}", exc_info=True)
            # Proceed without Plex check if server connection fails

        if user_plex:
            current_app.logger.debug(f"check_media_status: Vérification Plex pour '{title}' (type: {media_type})")
            if media_type == 'movie':
                year = parsed_info.get('year')
                status_info['details'] = f"{title} ({year})" if year else title
                try:
                    # Search returns a list, even if it's an exact match
                    plex_results = user_plex.library.search(title=title, year=year, libtype='movie', limit=5)
                    for movie_item in plex_results:
                        # Additional check to ensure it's the correct movie if year wasn't perfectly matched by search
                        if year and movie_item.year != year:
                            continue
                        if movie_item.title.lower() == title.lower(): # Stricter title match
                             # Check if media is available (has parts)
                            if hasattr(movie_item, 'media') and movie_item.media and \
                               hasattr(movie_item.media[0], 'parts') and movie_item.media[0].parts:
                                current_app.logger.info(f"check_media_status: '{title}' trouvé dans Plex.")
                                status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                                return status_info
                except Exception as e:
                    current_app.logger.error(f"check_media_status: Erreur lors de la recherche du film Plex '{title}': {e}", exc_info=True)

            elif media_type == 'episode':
                season_num = parsed_info.get('season')
                episode_num = parsed_info.get('episode')

                if not all([isinstance(season_num, int), isinstance(episode_num, int)]):
                    # If season/episode not parsed, can't check Plex accurately for episode
                    current_app.logger.warn(f"check_media_status: Saison/épisode non parsé pour '{release_title}', Plex check pour épisode ignoré.")
                else:
                    status_info['details'] = f"{title} - S{season_num:02d}E{episode_num:02d}"
                    try:
                        # Search for the show first
                        plex_shows = user_plex.library.search(title=title, libtype='show', limit=5)
                        if plex_shows:
                            for show_item in plex_shows: # Iterate in case of multiple matches for a show title
                                if show_item.title.lower() == title.lower(): # Stricter title match
                                    try:
                                        episode_item = show_item.episode(season=season_num, episode=episode_num)
                                        if episode_item and hasattr(episode_item, 'media') and episode_item.media and \
                                           hasattr(episode_item.media[0], 'parts') and episode_item.media[0].parts:
                                            current_app.logger.info(f"check_media_status: '{status_info['details']}' trouvé dans Plex.")
                                            status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                                            return status_info
                                    except NotFound:
                                        # Episode not found in this specific show, try next if multiple shows matched
                                        continue
                                    except Exception as e_ep:
                                        current_app.logger.error(f"check_media_status: Erreur lors de la récupération de l'épisode Plex pour '{title} S{season_num}E{episode_num}': {e_ep}", exc_info=True)
                                        break # Error with this show, stop trying
                            # If loop completes and episode not found in any matched show
                            current_app.logger.debug(f"check_media_status: Épisode '{status_info['details']}' non trouvé dans Plex après vérification des shows correspondants.")
                        else:
                            current_app.logger.debug(f"check_media_status: Série '{title}' non trouvée dans Plex.")
                    except Exception as e_show:
                        current_app.logger.error(f"check_media_status: Erreur lors de la recherche de la série Plex '{title}': {e_show}", exc_info=True)
        else:
            current_app.logger.warn("check_media_status: user_plex non disponible, Plex check ignoré.")

        # --- ÉTAPE 2: Si non présent dans Plex, vérifier Sonarr/Radarr (logique existante) ---
        current_app.logger.debug(f"check_media_status: '{release_title}' non trouvé dans Plex (ou Plex indisponible). Vérification Sonarr/Radarr.")

        if media_type == 'movie':
            # Year already parsed for Plex check
            year = parsed_info.get('year')
            # status_info['details'] already set
            radarr_results = search_radarr_by_title(title) # title is movie title
            found_in_radarr = None
            if radarr_results:
                # Filter by year if available, otherwise take first match
                if year:
                    found_in_radarr = next((m for m in radarr_results if m.get('year') == year and m.get('title', '').lower() == title.lower()), None)
                if not found_in_radarr: # If year-specific match failed or no year, try broader match
                    found_in_radarr = next((m for m in radarr_results if m.get('title', '').lower() == title.lower()), None)
            
            if not found_in_radarr:
                status_info.update({'status': 'Non Trouvé (Radarr)', 'badge_color': 'dark'})
            elif found_in_radarr.get('monitored'):
                status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
            else:
                status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})
            return status_info

        elif media_type == 'episode':
            # season_num, episode_num, title (series title), status_info['details'] already set/checked
            season_num = parsed_info.get('season') # Re-get in case it wasn't set due to not being int
            episode_num = parsed_info.get('episode')

            if not all([isinstance(season_num, int), isinstance(episode_num, int)]):
                 # This case should ideally be caught earlier, but as a safeguard
                current_app.logger.warn(f"check_media_status: Cannot check Sonarr for '{release_title}' due to missing season/episode numbers.")
                status_info.update({'status': 'Erreur Analyse S/E', 'badge_color': 'danger'})
                return status_info

            sonarr_results = search_sonarr_by_title(title) # title is series title
            if not sonarr_results:
                status_info.update({'status': 'Série non trouvée', 'badge_color': 'dark'})
                return status_info
            
            # Assuming the first result from sonarr_results is the most relevant if multiple are returned
            # A more robust approach might involve matching tvdbId if available from Prowlarr guid
            sonarr_series = next((s for s in sonarr_results if s.get('title','').lower() == title.lower()), sonarr_results[0])

            # Here, we need to check if the specific episode is monitored AND has a file in Sonarr's view
            # The current search_sonarr_by_title gives series info, not episode file status directly.
            # For simplicity, if series is monitored, assume episode is 'Manquant (Surveillé)' unless Plex said 'Déjà Présent'.
            # A deeper check would query Sonarr for the specific episode's status.
            if sonarr_series.get('monitored'):
                # TODO: Optionally, query Sonarr for this specific episode's file status for more accuracy
                # For now, if series is monitored and not in Plex, assume episode is wanted.
                status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
            else:
                status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})
            return status_info

        # If media_type is neither movie nor episode, or other unhandled case
        return status_info

    except Exception as e:
        current_app.logger.error(f"Erreur majeure dans check_media_status pour '{release_title}': {e}", exc_info=True)
        status_info.update({'status': 'Erreur Analyse Globale', 'badge_color': 'danger'})
        return status_info