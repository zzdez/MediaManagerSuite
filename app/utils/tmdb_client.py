# app/utils/tmdb_client.py (LA VRAIE CORRECTION)
import logging
from flask import current_app
from tmdbv3api import TMDb, Movie, Search

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

        # ** LA CORRECTION CRUCIALE EST ICI **
        original_lang = self.tmdb.language
        try:
            logger.info(f"Récupération des détails TMDb pour l'ID : {tmdb_id} en langue '{lang}'")

            # 1. On change la langue de l'instance
            self.tmdb.language = lang

            movie_api = Movie()

            # 2. On fait l'appel SANS le paramètre 'language'
            movie = movie_api.details(tmdb_id)

            # 3. On construit le dictionnaire de retour avec les bons noms de clés
            details = {
                'id': movie.id,
                'title': movie.title,
                'overview': movie.overview,
                'poster': f"https://image.tmdb.org/t/p/w500{movie.poster_path}" if movie.poster_path else "",
                'year': movie.release_date.split('-')[0] if hasattr(movie, 'release_date') and movie.release_date else 'N/A',
                'status': movie.status,
            }
            return details
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des détails TMDb pour {tmdb_id}: {e}", exc_info=True)
            return None
        finally:
            # 4. On restaure la langue d'origine, quoi qu'il arrive
            self.tmdb.language = original_lang

    def search_movie(self, title, lang='fr-FR'):
        """
        Recherche un film par titre sur TMDb.
        """
        if not self.api_key:
            logger.error("La clé API TMDb n'est pas disponible.")
            return []

        original_lang = self.tmdb.language
        try:
            logger.info(f"Recherche TMDb pour le titre : '{title}' en langue '{lang}'")
            # La langue pour la recherche est passée en paramètre de la méthode de recherche
            search = Search()
            results = search.movies(term=title, language=lang)

            # Formatter les résultats pour être cohérent avec ce que la route attend
            formatted_results = []
            for res in results:
                # On s'assure que les objets retournés ont bien les attributs nécessaires
                formatted_results.append({
                    'id': getattr(res, 'id', None),
                    'title': getattr(res, 'title', 'Titre non disponible'),
                    'original_title': getattr(res, 'original_title', 'Titre original non disponible'),
                    'overview': getattr(res, 'overview', ''),
                    'poster_path': getattr(res, 'poster_path', None),
                    'release_date': getattr(res, 'release_date', None),
                })
            return formatted_results
        except Exception as e:
            logger.error(f"Erreur lors de la recherche TMDb pour '{title}': {e}", exc_info=True)
            return []
        finally:
            # Pas besoin de gérer la langue de l'instance ici car elle est passée en paramètre de la recherche
            pass
