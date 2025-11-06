# -*- coding: utf-8 -*-
from flask import current_app
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from flask import session
from datetime import datetime
from collections import defaultdict

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
        Pour une série Plex, récupère un historique de visionnage détaillé en
        se basant sur l'historique de visionnage réel de l'utilisateur.
        """
        if not plex_show_obj or plex_show_obj.type != 'show':
            return None

        try:
            plex_show_obj.reload()

            # Récupérer tous les épisodes de la série pour avoir le compte total
            all_episodes = plex_show_obj.episodes()
            total_episodes_by_season = {}
            for ep in all_episodes:
                s_num = ep.seasonNumber
                if s_num not in total_episodes_by_season:
                    total_episodes_by_season[s_num] = 0
                total_episodes_by_season[s_num] += 1

            # Analyser l'historique de l'utilisateur pour trouver les épisodes vus de cette série
            user_history = self.plex.history(maxresults=5000) # Augmenter la limite pour être sûr
            watched_episodes_by_season = {}

            for entry in user_history:
                # On s'assure que l'entrée d'historique correspond bien à la série en cours
                if entry.grandparentRatingKey == plex_show_obj.ratingKey:
                    s_num = entry.parentIndex
                    if s_num not in watched_episodes_by_season:
                        watched_episodes_by_season[s_num] = set()
                    watched_episodes_by_season[s_num].add(entry.index)

            # Construire l'objet historique final
            final_history = {
                "poster_url": self.admin_plex.url(plex_show_obj.thumb, includeToken=True) if plex_show_obj.thumb else None,
                "is_fully_watched": plex_show_obj.isWatched, # Garde une vue d'ensemble simple
                "seasons": []
            }

            # Itérer sur les saisons existantes dans la série
            for season in plex_show_obj.seasons():
                s_num = season.seasonNumber
                if s_num == 0: continue # Ignorer les spéciaux

                watched_count = len(watched_episodes_by_season.get(s_num, set()))
                total_count = total_episodes_by_season.get(s_num, 0)

                season_data = {
                    "season_number": s_num,
                    "is_watched": watched_count > 0 and watched_count == total_count,
                    "total_episodes": total_count,
                    "watched_episodes": watched_count
                }
                final_history["seasons"].append(season_data)

            return final_history

        except Exception as e:
            current_app.logger.error(f"PlexClient: Erreur lors de la récupération de l'historique pour la série '{plex_show_obj.title}': {e}", exc_info=True)
            return None

    def get_movie_watch_history(self, plex_movie_obj):
        """
        Pour un film Plex, récupère un historique de visionnage simple.
        """
        if not plex_movie_obj or plex_movie_obj.type != 'movie':
            return None

        try:
            history = {
                "poster_url": self.admin_plex.url(plex_movie_obj.thumb, includeToken=True) if plex_movie_obj.thumb else None,
                "is_watched": plex_movie_obj.isWatched,
                "status": "Vu" if plex_movie_obj.isWatched else "Non vu"
            }
            return history
        except Exception as e:
            current_app.logger.error(f"PlexClient: Erreur lors de la récupération de l'historique pour le film '{plex_movie_obj.title}': {e}")
            return None

    def get_user_names(self):
        """
        Récupère un dictionnaire mappant les ID des utilisateurs Plex à leurs noms.
        """
        user_map = {}
        try:
            main_account = self.admin_plex.myPlexAccount()
            # Ajouter l'utilisateur principal
            main_title = main_account.title or main_account.username or f"Principal (ID: {main_account.id})"
            user_map[str(main_account.id)] = main_title

            # Ajouter les utilisateurs gérés
            for user in main_account.users():
                managed_title = user.title or f"Géré (ID: {user.id})"
                user_map[str(user.id)] = managed_title

            return user_map
        except Exception as e:
            current_app.logger.error(f"PlexClient: Impossible de récupérer la liste des utilisateurs: {e}")
            return {}

    def find_ghost_media_in_history(self, title_query):
        """
        Analyse l'historique Plex pour trouver des médias "fantômes" (supprimés)
        qui correspondent à une recherche par titre.
        VERSION OPTIMISÉE : Ne récupère que les informations de base pour un affichage rapide.
        """
        # Utilise un dictionnaire pour dédupliquer par titre
        ghosts = {}
        history = self.admin_plex.history(maxresults=10000)

        for entry in history:
            if entry.source() is None:
                title = None
                media_type = 'unknown'

                if entry.type == 'episode':
                    title = entry.grandparentTitle
                    media_type = 'show'
                elif entry.type == 'movie':
                    title = entry.title
                    media_type = 'movie'

                if title and title_query.lower() in title.lower():
                    media_key = title.lower()
                    if media_key not in ghosts:
                        ghosts[media_key] = {
                            'title': title,
                            'media_type': media_type,
                            'external_id': None,
                            'year': None,
                            'summary': "Ce média a été reconstitué à partir de l'historique de visionnage de Plex.",
                            'poster_url': None,
                            'archive_history': [] # Laissé vide pour être rempli à la demande
                        }

        return list(ghosts.values())

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
