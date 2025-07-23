# app/utils/tmdb_client.py
import logging
from flask import current_app
# CORRECTION : 'Details' a été retiré de la ligne suivante
from tmdbv3api import TMDb, Movie

logger = logging.getLogger(__name__)

class TheMovieDBClient:
    def __init__(self):
        self.api_key = current_app.config.get('TMDB_API_KEY')
        if not self.api_key:
            raise ValueError("La clé API TMDb (TMDB_API_KEY) n'est pas configurée.")
        self.tmdb = TMDb()
        self.tmdb.api_key = self.api_key
        self.tmdb.language = 'fr' # Langue par défaut

    def get_movie_details(self, tmdb_id, lang='fr-FR'):
        """
        Récupère les détails d'un film depuis TMDb en utilisant son ID et une langue spécifique.
        """
        if not self.api_key:
            logger.error("La clé API TMDb n'est pas disponible.")
            return None

        try:
            logger.info(f"Récupération des détails TMDb pour l'ID : {tmdb_id} en langue '{lang}'")
            movie_api = Movie()

            # La bibliothèque tmdbv3api utilise 'language' comme nom de paramètre.
            movie = movie_api.details(tmdb_id, language=lang)

            details = {
                'id': movie.id,
                'title': movie.title,
                'overview': movie.overview,
                'poster': f"https://image.tmdb.org/t/p/w500{movie.poster_path}" if movie.poster_path else "",
                'release_date': movie.release_date if hasattr(movie, 'release_date') else 'N/A',
                'year': movie.release_date.split('-')[0] if hasattr(movie, 'release_date') and movie.release_date else 'N/A',
                'status': movie.status,
            }
            return details
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des détails TMDb pour {tmdb_id}: {e}", exc_info=True)
            return None
