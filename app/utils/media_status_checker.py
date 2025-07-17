# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit # Ensure guessit is imported
from plexapi.exceptions import NotFound

from .arr_client import search_radarr_by_title, search_sonarr_by_title, get_arr_media_details # Added get_arr_media_details
from .plex_client import get_user_specific_plex_server, get_plex_admin_server, find_plex_media_by_external_id, find_plex_media_by_titles # Added Plex helpers

def _check_arr_status(parsed_info, status_info_ref, release_title_for_log):
    """Helper function to check Sonarr/Radarr status and return rich details."""
    media_type = parsed_info.get('type')
    arr_search_title = parsed_info.get('title')

    if not arr_search_title:
        status_info_ref.update({'status': 'Erreur Analyse Titre', 'badge_color': 'danger'})
        return status_info_ref

    current_app.logger.debug(f"_check_arr_status: Checking Arr for '{arr_search_title}' (type: {media_type})")

    arr_instance = None
    found_item = None

    if media_type == 'movie':
        arr_instance = "Radarr"
        year = parsed_info.get('year')
        radarr_results = search_radarr_by_title(arr_search_title)
        if radarr_results:
            if year:
                found_item = next((m for m in radarr_results if m.get('year') == year and m.get('title', '').lower() == arr_search_title.lower()), None)
            if not found_item:
                found_item = next((m for m in radarr_results if m.get('title', '').lower() == arr_search_title.lower()), None)

    elif media_type == 'episode':
        arr_instance = "Sonarr"
        sonarr_results = search_sonarr_by_title(arr_search_title)
        if sonarr_results:
            # La recherche renvoie déjà les résultats triés par pertinence
            found_item = sonarr_results[0]

    # --- Logique de mise à jour du statut ---
    if not found_item:
        status_info_ref.update({'status': f'Non Trouvé ({arr_instance})', 'badge_color': 'dark'})
    else:
        # On a trouvé l'item, on peuple les détails enrichis
        status_info_ref['status_details'] = {
            'title': found_item.get('title', 'Titre inconnu'),
            'year': found_item.get('year'),
            'id': found_item.get('id'), # ID interne de Sonarr/Radarr
            'tvdbId': found_item.get('tvdbId'),
            'tmdbId': found_item.get('tmdbId'),
            'instance': arr_instance.lower()
        }

        if found_item.get('monitored'):
            status_info_ref.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
        else:
            status_info_ref.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})

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
            # No proper title from guessit, Plex check is unlikely to succeed. Fallback to Arr check.
            return _check_arr_status(parsed_info, status_info, release_title)

        # --- NOUVEAU: ÉTAPE 1.5: Interroger Sonarr/Radarr pour enrichir les informations ---
        enriched_arr_info = None
        try:
            # Pass parsed_year from guessit to help get_arr_media_details select the correct item
            enriched_arr_info = get_arr_media_details(parsed_title, media_type, parsed_year)
            if enriched_arr_info:
                current_app.logger.info(f"check_media_status: Informations enrichies depuis Arr: {enriched_arr_info.get('canonical_title')}, TVDB: {enriched_arr_info.get('tvdb_id')}, TMDB: {enriched_arr_info.get('tmdb_id')}")
                # Update status_info['details'] with potentially more accurate title from Arr
                if enriched_arr_info.get('canonical_title'):
                    arr_title = enriched_arr_info.get('canonical_title')
                    arr_year = enriched_arr_info.get('year', parsed_year) # Prefer Arr year
                    if media_type == 'movie':
                        status_info['details'] = f"{arr_title} ({arr_year})" if arr_year else arr_title
                    elif media_type == 'episode' and isinstance(parsed_season, int) and isinstance(parsed_episode, int):
                         status_info['details'] = f"{arr_title} - S{parsed_season:02d}E{parsed_episode:02d}"
            else:
                current_app.logger.info(f"check_media_status: Aucune information enrichie obtenue depuis Arr pour '{parsed_title}'.")
        except Exception as e_arr_enrich:
            current_app.logger.error(f"check_media_status: Erreur lors de la récupération des détails enrichis depuis Arr pour '{parsed_title}': {e_arr_enrich}", exc_info=True)
            # Continue without enriched_arr_info if this step fails

        # --- ÉTAPE 2: Gestion du contexte Plex et Vérification ---
        plex_server_to_check = None
        # ... (existing logic for getting plex_server_to_check: user-specific or admin) ...
        # [This part of getting plex_server_to_check is kept from previous implementation]
        try:
            plex_server_to_check = get_user_specific_plex_server()
            if plex_server_to_check: current_app.logger.info("check_media_status: Utilisation du serveur Plex spécifique à l'utilisateur.")
            else: current_app.logger.info("check_media_status: Aucun serveur Plex spécifique à l'utilisateur trouvé.")
        except Exception as e_user_plex:
            current_app.logger.warn(f"check_media_status: Échec get_user_specific_plex_server: {e_user_plex}. Tentative avec serveur principal.")
        if not plex_server_to_check:
            try:
                plex_server_to_check = get_plex_admin_server()
                if plex_server_to_check: current_app.logger.info("check_media_status: Utilisation du serveur Plex principal.")
                else: current_app.logger.warn("check_media_status: Échec get_plex_admin_server. Check Plex ignoré.")
            except Exception as e_admin_plex:
                current_app.logger.error(f"check_media_status: Erreur connexion Plex principal: {e_admin_plex}", exc_info=True)
        # --- Fin de la récupération de plex_server_to_check ---

        plex_media_item_found = None # Will store the Show (for episodes) or Movie object

        if plex_server_to_check:
            current_app.logger.debug(f"check_media_status: Tentative de recherche Plex multi-niveaux pour '{status_info['details']}'")
            # NOUVEAU: Recherche multi-niveaux dans Plex
            if enriched_arr_info:
                # Priorité 1: Recherche par ID externe si disponible
                external_id_str = None
                if media_type == 'episode' and enriched_arr_info.get('tvdb_id'):
                    external_id_str = f"tvdb://{enriched_arr_info.get('tvdb_id')}"
                elif media_type == 'movie' and enriched_arr_info.get('tmdb_id'):
                    external_id_str = f"tmdb://{enriched_arr_info.get('tmdb_id')}"
                elif enriched_arr_info.get('imdb_id'): # Fallback to IMDb for both
                    external_id_str = f"imdb://{enriched_arr_info.get('imdb_id')}"

                if external_id_str:
                    plex_media_item_found = find_plex_media_by_external_id(plex_server_to_check, external_id_str, media_type)
                    if plex_media_item_found:
                        current_app.logger.info(f"Plex: Trouvé par ID externe '{external_id_str}': {plex_media_item_found.title}")

                # Priorité 2: Recherche par titres (canonique + alternatifs) si non trouvé par ID
                if not plex_media_item_found:
                    titles_to_try = [enriched_arr_info.get('canonical_title')] + enriched_arr_info.get('alternate_titles', [])
                    titles_to_try = [t for t in titles_to_try if t] # Remove None or empty strings
                    if titles_to_try:
                        # Use year from enriched_arr_info if available, else from guessit
                        search_year = enriched_arr_info.get('year', parsed_year)
                        plex_media_item_found = find_plex_media_by_titles(plex_server_to_check, titles_to_try, search_year, media_type)
                        if plex_media_item_found:
                             current_app.logger.info(f"Plex: Trouvé par liste de titres (e.g., '{titles_to_try[0]}'): {plex_media_item_found.title}")

            # Fallback: Si pas d'infos enrichies ou si les recherches ci-dessus échouent, utiliser le titre parsé simple
            if not plex_media_item_found:
                current_app.logger.debug(f"Plex: Recherche fallback avec titre parsé '{parsed_title}' et année '{parsed_year}'.")
                libtype_for_search = 'show' if media_type == 'episode' else media_type
                if libtype_for_search in ['show', 'movie']:
                    try:
                        results = plex_server_to_check.library.search(title=parsed_title, year=parsed_year, libtype=libtype_for_search, limit=1)
                        if results:
                            # Basic assumption: first result is good enough for this fallback
                            plex_media_item_found = results[0]
                            current_app.logger.info(f"Plex: Trouvé par recherche fallback simple: {plex_media_item_found.title}")
                    except Exception as e_fallback_search:
                        current_app.logger.error(f"Plex: Erreur recherche fallback: {e_fallback_search}")

            # --- Vérification de l'épisode/saison ou disponibilité du film ---
            if plex_media_item_found:
                if media_type == 'movie':
                    # Check availability (has parts)
                    if hasattr(plex_media_item_found, 'media') and plex_media_item_found.media and \
                       hasattr(plex_media_item_found.media[0], 'parts') and plex_media_item_found.media[0].parts:
                        current_app.logger.info(f"Plex: Film '{plex_media_item_found.title}' disponible.")
                        status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                        return status_info
                elif media_type == 'episode':
                    # Case 1: Specific episode check
                    if isinstance(parsed_season, int) and isinstance(parsed_episode, int):
                        current_app.logger.debug(f"Plex: Checking for specific episode S{parsed_season}E{parsed_episode} of '{plex_media_item_found.title}'.")
                        try:
                            episode_item = plex_media_item_found.episode(season=parsed_season, episode=parsed_episode)
                            if episode_item and hasattr(episode_item, 'media') and episode_item.media and \
                               hasattr(episode_item.media[0], 'parts') and episode_item.media[0].parts:
                                current_app.logger.info(f"Plex: Specific episode '{status_info['details']}' found and available.")
                                status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                                return status_info
                            else:
                                current_app.logger.debug(f"Plex: Specific episode S{parsed_season}E{parsed_episode} for '{plex_media_item_found.title}' found but no media/parts (unavailable).")
                        except NotFound:
                            current_app.logger.debug(f"Plex: Specific episode S{parsed_season}E{parsed_episode} not found for series '{plex_media_item_found.title}'.")
                        except Exception as e_ep_check:
                            current_app.logger.error(f"Plex: Error checking specific episode S{parsed_season}E{parsed_episode} for '{plex_media_item_found.title}': {e_ep_check}", exc_info=True)

                    # Case 2: Full season check (if specific episode not found or not specified)
                    # This 'elif' ensures it only runs if the specific episode check above didn't return.
                    # It also implies parsed_episode might be None or not an int if guessit identified a season pack.
                    elif isinstance(parsed_season, int) and not isinstance(parsed_episode, int): # Check for season if episode is not valid/specified
                        current_app.logger.debug(f"Plex: Checking for full season S{parsed_season} of '{plex_media_item_found.title}'.")
                        try:
                            season_obj = plex_media_item_found.season(season=parsed_season) # Get season by number
                            if season_obj and season_obj.episodes(): # Check if season exists and has any episodes
                                # Further check: are any of these episodes actually available?
                                # For simplicity, we consider the season "present" if the season object exists and lists episodes.
                                # A more granular check could iterate season_obj.episodes() and check their availability.
                                current_app.logger.info(f"Plex: Season {parsed_season} ('{season_obj.title}') found with episodes for series '{plex_media_item_found.title}'. Marking as 'Déjà Présent'.")
                                status_info['details'] = f"{plex_media_item_found.title} - Saison {parsed_season}" # Update details for season
                                status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                                return status_info
                            else:
                                current_app.logger.debug(f"Plex: Season {parsed_season} for '{plex_media_item_found.title}' found but no episodes listed or season object empty.")
                        except NotFound:
                            current_app.logger.debug(f"Plex: Season {parsed_season} not found for series '{plex_media_item_found.title}'.")
                        except Exception as e_season_check:
                            current_app.logger.error(f"Plex: Error checking season S{parsed_season} for '{plex_media_item_found.title}': {e_season_check}", exc_info=True)
                    else:
                        current_app.logger.warn(f"Plex: Parsed season/episode numbers for '{release_title}' (S{parsed_season}E{parsed_episode}) are not suitable for specific episode or season check.")
        else:
            current_app.logger.warn("check_media_status: Aucune instance de serveur Plex disponible. Le check Plex est ignoré.")

        # --- ÉTAPE 3: Si non présent dans Plex (ou Plex check ignoré), vérifier Sonarr/Radarr ---
        return _check_arr_status(parsed_info, status_info, release_title)

    except Exception as e:
        current_app.logger.error(f"Erreur majeure dans check_media_status pour '{release_title}': {e}", exc_info=True)
        status_info.update({'status': 'Erreur Analyse Globale', 'badge_color': 'danger'})
        return status_info