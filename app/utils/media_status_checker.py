# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit # Ensure guessit is imported
from plexapi.exceptions import NotFound

from .arr_client import search_radarr_by_title, search_sonarr_by_title, get_arr_media_details # Added get_arr_media_details
from .plex_client import get_user_specific_plex_server, get_plex_admin_server, find_plex_media_by_external_id, find_plex_media_by_titles # Added Plex helpers

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
                    if not all([isinstance(parsed_season, int), isinstance(parsed_episode, int)]):
                        current_app.logger.warn(f"Plex: Saison/épisode non parsé pour '{release_title}', impossible de vérifier l'épisode sur '{plex_media_item_found.title}'.")
                    else:
                        try:
                            # plex_media_item_found should be the show object here
                            episode_item = plex_media_item_found.episode(season=parsed_season, episode=parsed_episode)
                            if episode_item and hasattr(episode_item, 'media') and episode_item.media and \
                               hasattr(episode_item.media[0], 'parts') and episode_item.media[0].parts:
                                current_app.logger.info(f"Plex: Épisode '{status_info['details']}' disponible.")
                                status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                                return status_info
                        except NotFound:
                            current_app.logger.debug(f"Plex: Épisode S{parsed_season}E{parsed_episode} non trouvé pour la série '{plex_media_item_found.title}'.")
                        except Exception as e_ep_check:
                            current_app.logger.error(f"Plex: Erreur vérification épisode S{parsed_season}E{parsed_episode} pour '{plex_media_item_found.title}': {e_ep_check}")
        else:
            current_app.logger.warn("check_media_status: Aucune instance de serveur Plex disponible. Le check Plex est ignoré.")

        # --- ÉTAPE 3: Si non présent dans Plex (ou Plex check ignoré), vérifier Sonarr/Radarr ---
        return _check_arr_status(parsed_info, status_info, release_title)

    except Exception as e:
        current_app.logger.error(f"Erreur majeure dans check_media_status pour '{release_title}': {e}", exc_info=True)
        status_info.update({'status': 'Erreur Analyse Globale', 'badge_color': 'danger'})
        return status_info