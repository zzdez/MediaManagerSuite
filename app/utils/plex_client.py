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
