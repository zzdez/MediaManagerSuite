# app/utils/plex_client.py
# -*- coding: utf-8 -*-

from flask import current_app, session, flash
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound, Unauthorized

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

def get_user_specific_plex_server():
    current_app.logger.debug("--- Appel de get_user_specific_plex_server ---")
    """
    Returns a PlexServer instance connected as the user in session.
    Handles impersonation for managed users. Returns None on failure.
    """
    if 'plex_user_id' not in session:
        flash("Session utilisateur invalide. Veuillez vous reconnecter.", "danger")
        return None

    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')

    try:
        # This connection is primarily to get the main account or for impersonation token generation.
        # It's an admin connection.
        plex_admin_server_for_setup = PlexServer(plex_url, admin_token)
        # Note: get_main_plex_account_object itself creates a PlexServer instance.
        # To avoid creating two admin PlexServer objects back-to-back when not strictly necessary,
        # consider passing plex_admin_server_for_setup to get_main_plex_account_object
        # or refactoring get_main_plex_account_object.
        # For now, let's keep it as is, assuming the overhead is acceptable.
        main_account = get_main_plex_account_object()
        if not main_account: return None

        user_id_in_session = session.get('plex_user_id')

        if str(main_account.id) == user_id_in_session:
            current_app.logger.debug("Contexte: Utilisateur Principal (Admin).")
            # Return a direct admin connection
            return PlexServer(plex_url, admin_token)

        user_to_impersonate = next((u for u in main_account.users() if str(u.id) == user_id_in_session), None)
        if user_to_impersonate:
            try:
                # The machineIdentifier of the server is needed to get a token for a managed user.
                # We use the plex_admin_server_for_setup for this.
                managed_user_token = user_to_impersonate.get_token(plex_admin_server_for_setup.machineIdentifier)
                current_app.logger.debug(f"Contexte: Emprunt d'identité pour '{user_to_impersonate.title}'.")
                return PlexServer(plex_url, managed_user_token)
            except Exception as e:
                current_app.logger.error(f"Échec de l'emprunt d'identité pour {user_to_impersonate.title}: {e}")
                flash(f"Impossible d'emprunter l'identité de {user_to_impersonate.title}. Action annulée.", "danger")
                return None
        else:
            flash(f"Utilisateur de la session non trouvé. Reconnexion requise.", "warning")
            return None

    except Unauthorized: # Specifically catch Unauthorized for the initial PlexServer(plex_url, admin_token)
        current_app.logger.error("get_user_specific_plex_server: Token Plex admin invalide pour la configuration initiale.")
        flash("Erreur de configuration serveur (token admin).", "danger")
        return None
    except Exception as e:
        current_app.logger.error(f"Erreur majeure lors de l'obtention de la connexion utilisateur Plex : {e}", exc_info=True)
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
    # fetchItem is generally more reliable if the full GUID URI is correct for Plex.

    parsed_guid_for_search = external_id_str # Default to using it directly

    # Attempt with fetchItem first, as it's more direct if the GUID format is what Plex expects.
    try:
        # Plex's fetchItem can use various forms of GUIDs, including those with schemes.
        item = plex_server.fetchItem(external_id_str)
        if item:
            # If media_type is 'episode', we want the show. If fetchItem got an episode, get its grandparent (show).
            if media_type_from_guessit == 'episode' and item.type == 'episode':
                logger.debug(f"Plex Client: Found episode by ID '{external_id_str}', returning its show '{item.grandparentTitle}'.")
                return item.show() #.show() is an attribute that re-fetches the show
            elif media_type_from_guessit == 'episode' and item.type == 'show':
                logger.debug(f"Plex Client: Found show directly by ID '{external_id_str}'.")
                return item
            elif media_type_from_guessit == 'movie' and item.type == 'movie':
                logger.debug(f"Plex Client: Found movie by ID '{external_id_str}'.")
                return item
            else:
                logger.warn(f"Plex Client: Found item by ID '{external_id_str}' but type mismatch. Expected '{media_type_from_guessit}', got '{item.type}'.")
                return None # Type mismatch
        logger.debug(f"Plex Client: fetchItem for '{external_id_str}' returned None or non-matching type.")
    except NotFound:
        logger.debug(f"Plex Client: No item found with fetchItem for GUID '{external_id_str}'.")
    except Exception as e:
        logger.error(f"Plex Client: Error using fetchItem for GUID '{external_id_str}': {e}")

    # Fallback: try searching via library.search(guid=...)
    # This often requires the ID part without the scheme for some agents.
    # Example: if external_id_str is 'tvdb://12345', try searching guid='12345'
    # This part is tricky as Plex agent GUID formats vary.
    # For simplicity, we'll try with the original external_id_str first in search.
    # A more robust solution would parse common schemes like tvdb://, tmdb://, imdb://

    try:
        # Determine libtype for search
        libtype_for_search = 'show' if media_type_from_guessit == 'episode' else media_type_from_guessit
        if libtype_for_search not in ['show', 'movie']:
            logger.warn(f"Plex Client: Invalid libtype '{libtype_for_search}' for GUID search.")
            return None

        results = plex_server.library.search(guid=external_id_str, libtype=libtype_for_search, limit=1)
        if results:
            logger.info(f"Plex Client: Found media by GUID search '{external_id_str}': {results[0].title}")
            return results[0] # Returns the show or movie object

        # Try parsing common GUIDs if the above failed
        if '//' in external_id_str:
            parsed_id_only = external_id_str.split('//')[-1]
            results_parsed = plex_server.library.search(guid=parsed_id_only, libtype=libtype_for_search, limit=1)
            if results_parsed:
                logger.info(f"Plex Client: Found media by parsed GUID search '{parsed_id_only}': {results_parsed[0].title}")
                return results_parsed[0]

    except Exception as e:
        logger.error(f"Plex Client: Error searching Plex by GUID '{external_id_str}': {e}", exc_info=True)

    logger.warn(f"Plex Client: Could not find Plex media by external ID '{external_id_str}'.")
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
