# -*- coding: utf-8 -*-
from flask import current_app
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from flask import session

class PlexClient:
    """
    Client pour interagir avec le serveur Plex, capable d'agir en tant qu'admin
    ou d'emprunter l'identité d'un utilisateur géré.
    """
    def __init__(self, user_id=None):
        self.baseurl = current_app.config.get('PLEX_URL')
        admin_token = current_app.config.get('PLEX_TOKEN')
        if not self.baseurl or not admin_token:
            raise ValueError("PLEX_URL and PLEX_TOKEN must be configured in .env")

        self.admin_plex = PlexServer(self.baseurl, admin_token)
        self.user_plex = None

        if user_id:
            try:
                main_account = self.admin_plex.myPlexAccount()
                if str(main_account.id) == str(user_id):
                    self.user_plex = self.admin_plex
                else:
                    user_to_impersonate = next((u for u in main_account.users() if str(u.id) == str(user_id)), None)
                    if user_to_impersonate:
                        managed_user_token = user_to_impersonate.get_token(self.admin_plex.machineIdentifier)
                        self.user_plex = PlexServer(self.baseurl, managed_user_token)
                    else:
                        raise ValueError(f"User with ID {user_id} not found.")
            except Exception as e:
                current_app.logger.error(f"PlexClient: Failed to impersonate user {user_id}: {e}")
                self.user_plex = self.admin_plex
        else:
            self.user_plex = self.admin_plex

        self.plex = self.user_plex

    def get_item_by_rating_key(self, rating_key):
        """
        Récupère un objet média de Plex en utilisant son ratingKey.
        """
        try:
            return self.plex.fetchItem(rating_key)
        except Exception as e:
            current_app.logger.error(f"PlexClient: Impossible de trouver l'item avec le ratingKey {rating_key}: {e}")
            return None

    def get_show_watch_history(self, plex_show_obj):
        """
        Pour une série Plex, récupère un historique de visionnage détaillé.
        """
        if not plex_show_obj or plex_show_obj.type != 'show':
            return None

        try:
            plex_show_obj.reload()
            history = {
                "poster_url": plex_show_obj.posterUrl,
                "is_watched": plex_show_obj.isWatched,
                "seasons": []
            }

            for season in plex_show_obj.seasons():
                # Ignorer les saisons "Spéciales" (généralement saison 0)
                if season.seasonNumber == 0:
                    continue

                season_data = {
                    "season_number": season.seasonNumber,
                    "is_watched": season.isWatched,
                    "total_episodes": season.leafCount,
                    "watched_episodes": season.viewedLeafCount
                }
                history["seasons"].append(season_data)

            return history

        except Exception as e:
            current_app.logger.error(f"PlexClient: Erreur lors de la récupération de l'historique pour la série '{plex_show_obj.title}': {e}")
            return None

    def get_movie_watch_history(self, plex_movie_obj):
        """
        Pour un film Plex, récupère un historique de visionnage simple.
        """
        if not plex_movie_obj or plex_movie_obj.type != 'movie':
            return None

        try:
            history = {
                "poster_url": plex_movie_obj.posterUrl,
                "is_watched": plex_movie_obj.isWatched,
                "status": "Vu" if plex_movie_obj.isWatched else "Non vu"
            }
            return history
        except Exception as e:
            current_app.logger.error(f"PlexClient: Erreur lors de la récupération de l'historique pour le film '{plex_movie_obj.title}': {e}")
            return None

# --- Fonctions de compatibilité pour l'ancien code ---

def get_plex_admin_server():
    """Retourne une instance PlexServer pour l'admin."""
    try:
        return PlexClient().admin_plex
    except Exception as e:
        current_app.logger.error(f"Failed to get Plex admin server instance: {e}")
        return None

def get_main_plex_account_object():
    """Retourne l'objet MyPlexAccount principal."""
    try:
        admin_server = get_plex_admin_server()
        return admin_server.myPlexAccount() if admin_server else None
    except Exception as e:
        current_app.logger.error(f"Failed to get main Plex account object: {e}")
        return None

def get_user_specific_plex_server_from_id(user_id):
    """Retourne une instance PlexServer pour un user_id spécifique."""
    try:
        return PlexClient(user_id=user_id).user_plex
    except Exception as e:
        current_app.logger.error(f"Failed to get user-specific Plex server for user_id {user_id}: {e}")
        return None

def get_user_specific_plex_server():
    """Retourne une instance PlexServer pour l'utilisateur stocké en session."""
    user_id = session.get('plex_user_id')
    if not user_id:
        current_app.logger.warning("get_user_specific_plex_server called without user_id in session.")
        return None
    return get_user_specific_plex_server_from_id(user_id)

def find_plex_media_by_external_id(media_type, external_id):
    """
    Recherche sur tout le serveur Plex un média via son ID externe (TMDB ou TVDB).
    """
    admin_plex = get_plex_admin_server()
    if not admin_plex:
        return None

    source = 'tmdb' if media_type == 'movie' else 'tvdb'
    guid_str = f"{source}://{external_id}"

    try:
        # La recherche par GUID est supportée directement par l'API
        results = admin_plex.search(guid=guid_str)
        if results:
            return results[0]
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la recherche Plex par GUID {guid_str}: {e}")

    return None
