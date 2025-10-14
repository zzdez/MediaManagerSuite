# app/utils/tmdb_client.py (LA VRAIE CORRECTION)
import logging
from flask import current_app
from tmdbv3api import TMDb, Movie, Search, TV

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

        original_lang = self.tmdb.language # Sauvegarde la langue originale
        try:
            logger.info(f"Recherche TMDb pour le titre : '{title}' en langue '{lang}'")

            # 1. Changer la langue de l'instance globale avant l'appel
            self.tmdb.language = lang

            search = Search()

            # 2. Appeler la recherche SANS le paramètre 'language'
            results = search.movies(term=title)

            # 3. Formatter les résultats (votre code existant est parfait)
            formatted_results = []
            for res in results:
                # On force la conversion en str() pour les champs potentiellement problématiques
                # et on fournit des valeurs par défaut sûres.
                release_date = str(getattr(res, 'release_date', ''))

                formatted_results.append({
                    'id': getattr(res, 'id', None),
                    'title': str(getattr(res, 'title', 'Titre non disponible')),
                    'overview': str(getattr(res, 'overview', '')),
                    'poster_path': str(getattr(res, 'poster_path', '')),
                    'release_date': release_date,
                    'year': release_date.split('-')[0] if release_date else 'N/A',
                    'poster_url': f"https://image.tmdb.org/t/p/w92{getattr(res, 'poster_path', '')}" if getattr(res, 'poster_path', None) else ''
                })
            return formatted_results

        except Exception as e:
            logger.error(f"Erreur lors de la recherche TMDb pour '{title}': {e}", exc_info=True)
            return []
        finally:
            # 4. Restaurer la langue originale, quoi qu'il arrive
            self.tmdb.language = original_lang

    def get_series_details(self, tmdb_id, lang='fr-FR'):
        """
        Récupère les détails d'une série depuis TMDb en utilisant son ID et une langue spécifique.
        """
        if not self.api_key:
            logger.error("La clé API TMDb n'est pas disponible.")
            return None

        original_lang = self.tmdb.language
        try:
            logger.info(f"Récupération des détails de série TMDb pour l'ID : {tmdb_id} en langue '{lang}'")
            self.tmdb.language = lang
            tv_api = TV()
            series = tv_api.details(tmdb_id)
            external_ids = tv_api.external_ids(tmdb_id)
            tvdb_id = external_ids.get('tvdb_id') if external_ids else None

            details = {
                'id': series.id,
                'name': series.name,
                'overview': series.overview,
                'poster': f"https://image.tmdb.org/t/p/w500{series.poster_path}" if series.poster_path else "",
                'year': series.first_air_date.split('-')[0] if hasattr(series, 'first_air_date') and series.first_air_date else 'N/A',
                'status': series.status, # e.g., "Ended", "Returning Series"
                'tvdb_id': tvdb_id,
            }
            return details
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des détails de série TMDb pour {tmdb_id}: {e}", exc_info=True)
            return None
        finally:
            self.tmdb.language = original_lang
