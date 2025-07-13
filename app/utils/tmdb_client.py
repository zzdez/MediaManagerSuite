# app/utils/tmdb_client.py
import logging
from flask import current_app
from tmdbv3api import TMDb, Movie

logger = logging.getLogger(__name__)

class TheMovieDBClient:
    def __init__(self):
        self.api_key = current_app.config.get('TMDB_API_KEY')
        if not self.api_key:
            raise ValueError("La clé API TMDb (TMDB_API_KEY) n'est pas configurée.")
        self.tmdb = TMDb()
        self.tmdb.api_key = self.api_key
        self.tmdb.language = 'fr-FR' # Demander les infos en français par défaut

    def get_movie_details(self, tmdb_id):
        """
        Récupère les détails d'un film depuis TMDb en utilisant son ID.
        """
        if not self.api_key:
            logger.error("La clé API TMDb n'est pas disponible.")
            return None

        try:
            logger.info(f"Récupération des détails TMDb pour l'ID : {tmdb_id}")
            movie_api = Movie()
            movie = movie_api.details(tmdb_id)

            details = {
                'title': movie.title,
                'original_title': movie.original_title,
                'overview': movie.overview,
                'poster_path': f"https://image.tmdb.org/t/p/w500{movie.poster_path}" if movie.poster_path else None,
                'year': movie.release_date.split('-')[0] if movie.release_date else None,
            }
            return details
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des détails TMDb pour {tmdb_id}: {e}")
            return None
