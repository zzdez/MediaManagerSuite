# Fichier : app/utils/tvdb_client.py (Version Simple et Correcte)

import logging
from tvdb_v4_official import TVDB
from config import Config

logger = logging.getLogger(__name__)

class CustomTVDBClient:
    def __init__(self):
        self.api_key = Config.TVDB_API_KEY
        self.pin = Config.TVDB_PIN
        self.client = None
        if self.api_key and self.pin:
            try:
                self.client = TVDB(self.api_key, self.pin)
            except Exception as e:
                logger.error(f"Failed to initialize TVDB client: {e}")

    def get_series_details_by_id(self, tvdb_id, lang='fra'):
        if not self.client: return None
        try:
            details = self.client.get_series(tvdb_id)
            if not details: return None
            try:
                translation = self.client.get_series_translation(tvdb_id, lang)
                if translation and translation.get('overview'):
                    details['seriesName'] = translation.get('name') or details.get('seriesName')
                    details['overview'] = translation.get('overview') or details.get('overview')
            except Exception:
                pass # On ignore si la traduction échoue
            return details
        except Exception:
            return None

    def search_series(self, title, lang='fra'):
        """
        Recherche une série par son titre, en priorisant une langue.
        """
        if not self.client:
            logger.error("Client TVDB non initialisé, recherche impossible.")
            return []
        try:
            logger.info(f"Recherche TVDB pour le titre : '{title}' en langue '{lang}'")
            # La librairie tvdb_v4_official permet de passer des kwargs qui sont ajoutés aux paramètres de la requête
            results = self.client.search(query=title, lang=lang)
            return results if results else []
        except Exception as e:
            logger.error(f"Erreur lors de la recherche TVDB pour '{title}': {e}", exc_info=True)
            return []

    def search_and_translate_series(self, title, lang='fra'):
        """
        Recherche une série, puis enrichit chaque résultat avec la traduction
        dans la langue spécifiée. Retourne une liste de dictionnaires.
        """
        if not self.client:
            logger.error("Client TVDB non initialisé, recherche impossible.")
            return []

        try:
            logger.info(f"Recherche et traduction TVDB pour : '{title}' en langue '{lang}'")

            search_results = self.client.search(query=title)

            if not search_results:
                return []

            enriched_results = []
            for series_summary in search_results:
                try:
                    # On transforme l'objet résultat en un dictionnaire propre
                    series_data = {
                        'tvdb_id': series_summary.get('tvdb_id'),
                        'name': series_summary.get('name'),
                        'year': series_summary.get('year'),
                        'overview': series_summary.get('overview'),
                        'image_url': series_summary.get('image_url'),
                        'slug': series_summary.get('slug')
                    }

                    translation = self.client.get_series_translation(series_summary['tvdb_id'], lang)

                    if translation:
                        series_data['name'] = translation.get('name') or series_data['name']
                        series_data['overview'] = translation.get('overview') or series_data['overview']

                    enriched_results.append(series_data)

                except Exception as e_translate:
                    logger.warning(f"Impossible de traduire la série ID {series_summary.get('tvdb_id')}: {e_translate}")
                    if 'tvdb_id' in series_summary:
                        enriched_results.append(series_summary) # Ajoute l'original en cas d'erreur

            return enriched_results

        except Exception as e:
            logger.error(f"Erreur majeure lors de la recherche et traduction TVDB pour '{title}': {e}", exc_info=True)
            return []