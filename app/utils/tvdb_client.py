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
            logger.debug(f"TVDB details response for ID {tvdb_id}: {details}") # LOG DE DÉBOGAGE
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
        [VERSION OPTIMISÉE]
        Recherche une série par son titre, en ciblant le type 'series',
        et gère la traduction de manière plus efficace.
        """
        if not self.client:
            logger.error("Client TVDB non initialisé.")
            return []

        logger.info(f"--- Recherche TVDB optimisée pour '{title}' ---")

        try:
            # ÉTAPE 1: Recherche ciblée sur le type 'series'
            search_results = self.client.search(query=title, type='series', lang=lang)

            if not search_results:
                logger.info("  -> Aucun résultat de type 'série' trouvé.")
                return []

            logger.info(f"  -> {len(search_results)} série(s) potentielle(s) trouvée(s).")

            enriched_results = []
            # On ne traite que les 5 premiers résultats pour la performance
            for series_summary in search_results[:5]:
                tvdb_id = series_summary.get('tvdb_id')
                if not tvdb_id:
                    continue

                # On commence avec les données de base
                series_data = {
                    'tvdb_id': tvdb_id,
                    'name': series_summary.get('name'),
                    'year': series_summary.get('year'),
                    'overview': series_summary.get('overview'),
                    'poster_url': series_summary.get('image_url'),
                    'slug': series_summary.get('slug')
                }

                # ÉTAPE 2: Tentative de traduction, gérée gracieusement
                try:
                    translation = self.client.get_series_translation(tvdb_id, lang)
                    if translation:
                        logger.info(f"  -> Traduction trouvée pour '{series_data['name']}' (ID: {tvdb_id})")
                        series_data['name'] = translation.get('name') or series_data['name']
                        series_data['overview'] = translation.get('overview') or series_data['overview']
                except ValueError as e:
                    # Cette exception est levée par la librairie pour une "NotFoundException".
                    # C'est un cas normal (pas de traduction), donc on ne logue qu'en DEBUG.
                    logger.debug(f"  -> Pas de traduction '{lang}' trouvée pour l'ID {tvdb_id}. C'est un cas normal.")
                except Exception as e_translate:
                    # Les autres erreurs sont plus graves
                    logger.error(f"  -> Erreur inattendue lors de la traduction pour l'ID {tvdb_id}: {e_translate}")

                enriched_results.append(series_data)

            logger.info("--- Fin de la recherche TVDB optimisée ---")
            return enriched_results

        except Exception as e:
            logger.error(f"Erreur majeure dans search_and_translate_series pour '{title}': {e}", exc_info=True)
            return []