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
        [VERSION DE DÉBOGAGE]
    Recherche une série et enrichit chaque résultat avec la traduction.
    """
    if not self.client:
        logger.error("Client TVDB non initialisé.")
        return []

    logger.info(f"--- DÉBUT RECHERCHE & TRADUCTION TVDB POUR '{title}' ---")

    try:
        search_results = self.client.search(query=title)
        if not search_results:
            logger.info("  -> Recherche initiale n'a retourné aucun résultat.")
            return []

        logger.info(f"  -> Recherche initiale a trouvé {len(search_results)} résultat(s).")

        enriched_results = []
        for i, series_summary in enumerate(search_results):
            tvdb_id = series_summary.get('tvdb_id')
            logger.info(f"\n  [Résultat {i+1}/{len(search_results)}] Traitement de l'ID TVDb : {tvdb_id} ('{series_summary.get('name')}')")

            series_data = {
                'tvdb_id': tvdb_id,
                'name': series_summary.get('name'),
                'year': series_summary.get('year'),
                'overview': series_summary.get('overview'),
                'poster_url': series_summary.get('image_url'),
                'slug': series_summary.get('slug')
            }
            logger.debug(f"    Données de base (anglais) : {series_data}")

            try:
                logger.info(f"    -> Tentative de récupération de la traduction en '{lang}'...")
                translation = self.client.get_series_translation(tvdb_id, lang)

                if translation:
                    logger.info(f"    -> SUCCÈS : Traduction trouvée !")
                    logger.debug(f"    Contenu de la traduction : {translation}")

                    series_data['name'] = translation.get('name') or series_data['name']
                    series_data['overview'] = translation.get('overview') or series_data['overview']

                    if translation.get('name'):
                        logger.info(f"    -> Titre mis à jour en : '{translation.get('name')}'")
                    if translation.get('overview'):
                        logger.info(f"    -> Synopsis mis à jour.")

                else:
                    logger.warning(f"    -> ÉCHEC : La fonction get_series_translation a retourné None ou vide.")

                enriched_results.append(series_data)

            except Exception as e_translate:
                logger.error(f"    -> ERREUR CRITIQUE lors de la récupération de la traduction pour l'ID {tvdb_id}: {e_translate}", exc_info=True)
                enriched_results.append(series_summary) # On ajoute l'original en cas d'erreur

        logger.info("--- FIN RECHERCHE & TRADUCTION TVDB ---")
        return enriched_results

    except Exception as e:
        logger.error(f"Erreur majeure dans search_and_translate_series pour '{title}': {e}", exc_info=True)
        return []