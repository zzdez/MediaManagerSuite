# app/utils/plex_client.py
# -*- coding: utf-8 -*-

import logging # Added logging import
from flask import current_app, session, flash
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound, Unauthorized

logger = logging.getLogger(__name__) # Defined module-level logger

# --- Fonctions Utilitaires ---

def get_main_plex_account_object():
    plex_url = current_app.config.get('PLEX_URL')
    plex_token = current_app.config.get('PLEX_TOKEN')
    if not plex_url or not plex_token:
        current_app.logger.error("get_main_plex_account_object: Configuration Plex (URL/Token) manquante.")
        flash("Configuration Plex (URL/Token) du serveur principal manquante.", "danger")
        return None
    try:
        plex_admin_server = PlexServer(plex_url, plex_token)
        main_account = plex_admin_server.myPlexAccount()
        return main_account
    except Unauthorized:
        current_app.logger.error("get_main_plex_account_object: Token Plex principal invalide ou expiré.")
        flash("Token Plex principal invalide ou expiré. Impossible d'accéder aux informations du compte.", "danger")
        session.clear()
        return None
    except Exception as e:
        current_app.logger.error(f"get_main_plex_account_object: Erreur inattendue: {e}", exc_info=True)
        flash("Erreur inattendue lors de la récupération des informations du compte Plex principal.", "danger")
        return None

def get_plex_admin_server():
    """Helper pour obtenir une connexion admin à Plex. Retourne None en cas d'échec."""
    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')
    if not plex_url or not admin_token:
        current_app.logger.error("get_plex_admin_server: Configuration Plex admin manquante.")
        flash("Configuration Plex admin manquante.", "danger")
        return None
    try:
        return PlexServer(plex_url, admin_token)
    except Exception as e:
        current_app.logger.error(f"Erreur de connexion au serveur Plex admin: {e}", exc_info=True)
        flash("Erreur de connexion au serveur Plex admin.", "danger")
        return None

def get_user_specific_plex_server_from_id(user_id):
    """
    Returns a PlexServer instance for a specific user ID.
    Handles impersonation for managed users. Returns None on failure.
    """
    current_app.logger.debug(f"--- Appel de get_user_specific_plex_server_from_id pour user_id: {user_id} ---")
    if not user_id:
        flash("Aucun ID utilisateur fourni.", "danger")
        current_app.logger.warning("get_user_specific_plex_server_from_id: 'user_id' manquant.")
        return None

    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')

    main_account = get_main_plex_account_object()
    if not main_account:
        current_app.logger.error("get_user_specific_plex_server_from_id: Échec de la récupération du compte principal Plex.")
        return None

    try:
        if str(main_account.id) == user_id:
            current_app.logger.debug("Contexte: Utilisateur Principal (Admin).")
            return get_plex_admin_server()

        user_to_impersonate = next((u for u in main_account.users() if str(u.id) == user_id), None)
        if user_to_impersonate:
            admin_server_for_token = get_plex_admin_server()
            if not admin_server_for_token:
                return None
            managed_user_token = user_to_impersonate.get_token(admin_server_for_token.machineIdentifier)
            current_app.logger.debug(f"Contexte: Emprunt d'identité pour '{user_to_impersonate.title}'.")
            return PlexServer(plex_url, managed_user_token)
        else:
            flash(f"Utilisateur (ID: {user_id}) non trouvé. Reconnexion requise.", "warning")
            return None

    except Unauthorized as e:
        current_app.logger.error(f"Erreur d'autorisation dans get_user_specific_plex_server_from_id: {e}")
        flash("Erreur d'autorisation. Le token Plex est peut-être invalide.", "danger")
        return None
    except Exception as e:
        current_app.logger.error(f"Erreur majeure dans get_user_specific_plex_server_from_id : {e}", exc_info=True)
        flash(f"Une erreur inattendue est survenue: {e}", "danger")
        return None

def get_user_specific_plex_server():
    """
    Returns a PlexServer instance connected as the user in session.
    Handles impersonation for managed users. Returns None on failure.
    """
    current_app.logger.debug("--- Appel de get_user_specific_plex_server ---")
    if 'plex_user_id' not in session:
        flash("Session utilisateur invalide ou expirée. Veuillez sélectionner un utilisateur.", "danger")
        current_app.logger.warning("get_user_specific_plex_server: 'plex_user_id' non trouvé dans la session.")
        return None

    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')

    # --- CORRECTION MAJEURE : On sort cet appel du bloc try/except ---
    # get_main_plex_account_object a sa propre gestion d'erreurs robuste.
    main_account = get_main_plex_account_object()
    if not main_account:
        # Si cette fonction échoue, elle a déjà flashé un message. On s'arrête ici.
        current_app.logger.error("get_user_specific_plex_server: Échec de la récupération du compte principal Plex.")
        return None

    try:
        user_id_in_session = session.get('plex_user_id')
        # On vérifie que user_id_in_session n'est pas None
        if not user_id_in_session:
            flash("ID utilisateur manquant dans la session. Veuillez sélectionner un utilisateur.", "danger")
            return None

        if str(main_account.id) == user_id_in_session:
            current_app.logger.debug("Contexte: Utilisateur Principal (Admin).")
            # On réutilise la fonction get_plex_admin_server pour la cohérence
            return get_plex_admin_server()

        # Emprunt d'identité pour un utilisateur géré
        user_to_impersonate = next((u for u in main_account.users() if str(u.id) == user_id_in_session), None)
        if user_to_impersonate:
            admin_server_for_token = get_plex_admin_server()
            if not admin_server_for_token:
                # get_plex_admin_server gère déjà le flash
                return None
            managed_user_token = user_to_impersonate.get_token(admin_server_for_token.machineIdentifier)
            current_app.logger.debug(f"Contexte: Emprunt d'identité pour '{user_to_impersonate.title}'.")
            return PlexServer(plex_url, managed_user_token)
        else:
            flash(f"Utilisateur de la session (ID: {user_id_in_session}) non trouvé parmi les utilisateurs gérés. Reconnexion requise.", "warning")
            return None

    except Unauthorized as e:
        current_app.logger.error(f"Erreur d'autorisation dans get_user_specific_plex_server: {e}")
        flash("Erreur d'autorisation. Le token Plex est peut-être invalide.", "danger")
        return None
    except Exception as e:
        current_app.logger.error(f"Erreur majeure dans get_user_specific_plex_server : {e}", exc_info=True)
        flash(f"Une erreur inattendue est survenue: {e}", "danger")
        return None

def find_plex_media_by_external_id(plex_server, external_id_str: str, media_type_from_guessit: str):
    """
    Finds a Plex media item (show or movie) using an external ID string (e.g., "tvdb://12345").
    For 'episode' media_type, it aims to return the show.
    Returns the Plex item or None.
    """
    if not plex_server or not external_id_str:
        return None

    # Plex GUIDs often don't include the "scheme" part like "tvdb://" in its internal guids field for search.
    # We might need to parse the ID out of external_id_str if it includes such schemes.
    # Example: external_id_str could be "tvdb://12345" or just "12345" if type is known.
    # Plex's search for guid usually expects the raw ID part for some agents, or full for others.
    # The fetchItem method is problematic for scheme-based GUIDs like tvdb:// as it forms invalid URLs.
    # We will primarily rely on library.search(guid=...) which is more robust for these.

    libtype_for_search = 'show' if media_type_from_guessit == 'episode' else media_type_from_guessit
    if libtype_for_search not in ['show', 'movie']:
        logger.warn(f"Plex Client: Invalid libtype '{libtype_for_search}' for GUID search of '{external_id_str}'.")
        return None

    # Attempt 1: Search with the full external_id_str (e.g., "tvdb://12345")
    try:
        logger.debug(f"Plex Client: Attempting GUID search with full ID '{external_id_str}' and libtype '{libtype_for_search}'.")
        results = plex_server.library.search(guid=external_id_str, libtype=libtype_for_search, limit=1)
        if results:
            item = results[0]
            # Ensure correct type if 'episode' was requested (we want the show)
            if media_type_from_guessit == 'episode' and item.type == 'episode':
                 logger.info(f"Plex Client: Found episode by full GUID search '{external_id_str}', returning show: {item.show().title}")
                 return item.show()
            elif item.type == libtype_for_search: # Covers show for episode type, or movie for movie type
                 logger.info(f"Plex Client: Found media by full GUID search '{external_id_str}': {item.title}")
                 return item
            else:
                 logger.warn(f"Plex Client: Full GUID search for '{external_id_str}' found item of type '{item.type}', expected '{libtype_for_search}'.")

    except Exception as e:
        logger.error(f"Plex Client: Error searching Plex by full GUID '{external_id_str}': {e}", exc_info=True)

    # Attempt 2: Parse common schemes and search with only the ID part (e.g., "12345" from "tvdb://12345")
    if '//' in external_id_str:
        parsed_id_only = external_id_str.split('//')[-1]
        if parsed_id_only and parsed_id_only != external_id_str: # Ensure parsing actually changed something
            try:
                logger.debug(f"Plex Client: Attempting GUID search with parsed ID '{parsed_id_only}' and libtype '{libtype_for_search}'.")
                results_parsed = plex_server.library.search(guid=parsed_id_only, libtype=libtype_for_search, limit=1)
                if results_parsed:
                    item = results_parsed[0]
                    if media_type_from_guessit == 'episode' and item.type == 'episode':
                        logger.info(f"Plex Client: Found episode by parsed GUID search '{parsed_id_only}', returning show: {item.show().title}")
                        return item.show()
                    elif item.type == libtype_for_search:
                        logger.info(f"Plex Client: Found media by parsed GUID search '{parsed_id_only}': {item.title}")
                        return item
                    else:
                        logger.warn(f"Plex Client: Parsed GUID search for '{parsed_id_only}' found item of type '{item.type}', expected '{libtype_for_search}'.")
            except Exception as e:
                logger.error(f"Plex Client: Error searching Plex by parsed GUID '{parsed_id_only}': {e}", exc_info=True)

    # If fetchItem was considered for specific Plex internal GUIDs (not scheme-based ones), that logic could go here.
    # For now, relying on library.search(guid=...) is safer for external IDs.
    # Example: If external_id_str was something like "/library/metadata/xxxxx" (a rating key)
    # if external_id_str.startswith("/library/metadata/"):
    #     try:
    #         item = plex_server.fetchItem(external_id_str)
    #         # ... (type checking as above) ...
    #         return item
    #     except NotFound:
    #          logger.debug(f"Plex Client: fetchItem for direct key '{external_id_str}' not found.")
    #     except Exception as e:
    #          logger.error(f"Plex Client: Error with fetchItem for direct key '{external_id_str}': {e}")

    logger.warn(f"Plex Client: Could not find Plex media by external ID '{external_id_str}' after all attempts.")
    return None

def find_plex_media_by_titles(plex_server, titles_list: list, year: int, media_type_from_guessit: str):
    """
    Finds a Plex media item by iterating through a list of titles.
    Returns the Plex item or None.
    """
    if not plex_server or not titles_list:
        return None

    libtype_for_search = 'show' if media_type_from_guessit == 'episode' else media_type_from_guessit
    if libtype_for_search not in ['show', 'movie']:
        logger.warn(f"Plex Client: Invalid libtype '{libtype_for_search}' for titles search.")
        return None

    for title_to_search in titles_list:
        if not title_to_search: continue # Skip empty titles

        try:
            logger.debug(f"Plex Client: Searching Plex for title '{title_to_search}', year '{year}', type '{libtype_for_search}'.")
            results = plex_server.library.search(title=title_to_search, year=year, libtype=libtype_for_search, limit=5)
            if results:
                # Prefer exact title match (case-insensitive) if multiple results
                for item in results:
                    if item.title.lower() == title_to_search.lower():
                        # If year was provided for search, ensure Plex item's year also matches
                        if year and hasattr(item, 'year') and item.year != year:
                            logger.debug(f"Plex Client: Title '{title_to_search}' matched but year mismatch (Plex: {item.year}, Expected: {year}). Skipping.")
                            continue
                        logger.info(f"Plex Client: Found exact title match for '{title_to_search}' (Year: {item.year if hasattr(item, 'year') else 'N/A'}).")
                        return item

                # If no exact title match, but got results, consider the first one (less ideal)
                # This could be refined further based on confidence scores if Plex API provides them via plexapi
                logger.info(f"Plex Client: Found potential match for title '{title_to_search}' (first result: {results[0].title}). Year matching: {year == results[0].year if hasattr(results[0], 'year') and year else 'N/A or no year given'}.")
                # Ensure year matches if one was provided for the search
                if year and hasattr(results[0], 'year') and results[0].year == year:
                    return results[0]
                elif not year: # If no year was provided for search, first result is a candidate
                    return results[0]
                # else: year was provided but didn't match the first result, so continue to next title in titles_list

        except Exception as e:
            logger.error(f"Plex Client: Error searching Plex by title '{title_to_search}': {e}", exc_info=True)
            # Continue to the next title if an error occurs for one
            continue

    logger.warn(f"Plex Client: Could not find Plex media by any of the titles: {titles_list} (Year: {year}).")
    return None

def trigger_plex_scan(*library_keys: int):
    """
    Triggers a library scan on the Plex server for the given library keys.
    Uses an admin connection to ensure permissions. Logs successes and failures.
    """
    if not library_keys:
        logger.warning("trigger_plex_scan called with no library keys.")
        return

    plex_server = get_plex_admin_server()
    if not plex_server:
        logger.error("trigger_plex_scan: Could not get Plex admin server to trigger scan.")
        return

    scanned_libs = []
    failed_libs = []
    unique_keys = set(library_keys) # Ensure we don't scan the same library multiple times

    logger.info(f"Triggering Plex scan for library keys: {unique_keys}")
    for key in unique_keys:
        try:
            library = plex_server.library.sectionByID(key)
            logger.info(f"Scanning library: '{library.title}' (Key: {key})")
            library.update()
            scanned_libs.append(library.title)
        except NotFound:
            logger.error(f"trigger_plex_scan: Library with key {key} not found.")
            failed_libs.append(str(key))
        except Exception as e:
            logger.error(f"trigger_plex_scan: Failed to scan library key {key}: {e}", exc_info=True)
            failed_libs.append(str(key))

    if scanned_libs:
        logger.info(f"Successfully triggered scan for libraries: {', '.join(scanned_libs)}")
    if failed_libs:
        logger.error(f"Failed to trigger scan for library keys: {', '.join(failed_libs)}")
