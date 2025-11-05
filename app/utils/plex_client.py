# -*- coding: utf-8 -*-
from flask import current_app
from plexapi.server import PlexServer

class PlexClient:
    """
    Client pour interagir avec le serveur Plex.
    """
    def __init__(self):
        self.baseurl = current_app.config.get('PLEX_URL')
        self.token = current_app.config.get('PLEX_TOKEN')
        if not self.baseurl or not self.token:
            raise ValueError("PLEX_URL and PLEX_TOKEN must be configured in .env")
        self.plex = PlexServer(self.baseurl, self.token)

    def get_item_by_rating_key(self, rating_key):
        """
        Récupère un objet média de Plex en utilisant son ratingKey.
        """
        try:
            return self.plex.fetchItem(rating_key)
        except Exception as e:
            current_app.logger.error(f"PlexClient: Impossible de trouver l'item avec le ratingKey {rating_key}: {e}")
            return None

    def get_watched_seasons_tags(self, plex_show_obj):
        """
        Pour une série Plex donnée, retourne une liste de tags pour chaque saison entièrement vue.
        """
        if not plex_show_obj or plex_show_obj.type != 'show':
            return []

        tags = []
        try:
            # Recharger l'objet pour s'assurer que toutes les informations sont à jour
            plex_show_obj.reload()

            # Tag global si au moins un épisode a été vu
            if plex_show_obj.viewedLeafCount > 0:
                tags.append('vu')

            for season in plex_show_obj.seasons():
                # On ne traite pas la saison des "specials"
                if season.seasonNumber == 0:
                    continue

                # isWatched est True si tous les épisodes de la saison sont vus
                if season.isWatched:
                    tag = f"saison-{str(season.seasonNumber).zfill(2)}-vue"
                    tags.append(tag)

        except Exception as e:
            current_app.logger.error(f"PlexClient: Erreur lors de la récupération des saisons vues pour '{plex_show_obj.title}': {e}")

        return tags

    def get_movie_watched_tags(self, plex_movie_obj):
        """
        Pour un film Plex donné, retourne un tag si le film a été vu.
        """
        if not plex_movie_obj or plex_movie_obj.type != 'movie':
            return []

        tags = []
        try:
            if plex_movie_obj.isWatched:
                tags.append('vu')
        except Exception as e:
            current_app.logger.error(f"PlexClient: Erreur lors de la vérification du statut de visionnage pour le film '{plex_movie_obj.title}': {e}")

        return tags
