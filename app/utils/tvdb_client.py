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
            series_data = self.client.get_series(tvdb_id)
            if not series_data:
                return None

            # --- DÉBUT DU BLOC DE DÉBOGAGE DÉTAILLÉ ---
            logger.info(f"--- DÉBUT DÉBOGAGE TVDB ID: {tvdb_id} ---")
            logger.info(f"Type de l'objet 'series_data': {type(series_data)}")
            if isinstance(series_data, dict):
                logger.info(f"Clés du dictionnaire 'series_data': {series_data.keys()}")
            else:
                logger.info(f"Attributs de l'objet 'series_data': {dir(series_data)}")
            logger.info(f"Valeur de 'series_data': {series_data}")
            logger.info(f"--- FIN DÉBOGAGE TVDB ---")
            # --- FIN DU BLOC DE DÉBOGAGE DÉTAILLÉ ---

            simple_details = {
                'id': series_data.get('id'),
                'name': series_data.get('name'),
                'year': series_data.get('year'),
                'overview': series_data.get('overview'),
                'image': series_data.get('image') or ''
            }
            try:
                translation = self.client.get_series_translation(tvdb_id, lang)
                if translation:
                    # On utilise la traduction seulement si elle n'est pas vide ou composée d'espaces
                    translated_name = translation.get('name')
                    if translated_name and translated_name.strip():
                        simple_details['name'] = translated_name

                    translated_overview = translation.get('overview')
                    if translated_overview and translated_overview.strip():
                        simple_details['overview'] = translated_overview
            except Exception:
                logger.debug(f"Pas de traduction '{lang}' pour la série ID {tvdb_id}.")

            return simple_details

        except Exception as e:
            logger.error(f"Une erreur inattendue est survenue dans get_series_details_by_id pour {tvdb_id}: {e}")
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
                # On récupère les détails complets pour avoir le nom original non traduit (avec fallback)
                try:
                    full_series_details = self.client.get_series(tvdb_id)
                    original_name = full_series_details.get('name') if full_series_details else series_summary.get('name')
                except Exception as e:
                    logger.warning(f"  -> Impossible de récupérer les détails complets pour l'ID {tvdb_id} afin d'obtenir le nom original. Erreur: {e}")
                    original_name = series_summary.get('name') # Fallback sécurisé

                series_data = {
                    'tvdb_id': tvdb_id,
                    'name': series_summary.get('name'),
                    'original_name': original_name,
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

    def get_season_episode_counts(self, tvdb_id):
        """
        Récupère le nombre d'épisodes par saison en utilisant la méthode 'default' qui a fonctionné.
        """
        if not self.client:
            logger.error("Client TVDB non initialisé.")
            return {}

        logger.info(f"Récupération des épisodes avec season_type='default' pour TVDB ID: {tvdb_id}")

        try:
            episodes_response = self.client.get_series_episodes(tvdb_id, season_type='default')

            if not episodes_response or 'episodes' not in episodes_response or not episodes_response['episodes']:
                logger.warning(f"Aucune donnée d'épisode 'default' trouvée pour la série TVDB ID {tvdb_id}.")
                return {}

            # --- LOG DE DÉBOGAGE DE LA STRUCTURE D'UN ÉPISODE ---
            if episodes_response['episodes']:
                logger.info(f"Structure du premier épisode: {episodes_response['episodes'][0]}")
            # --- FIN DU LOG ---

            episode_counts = {}
            for episode in episodes_response['episodes']:
                # On inspecte la clé de la saison. C'est probablement 'seasonNumber' ou 'airedSeason'
                season_number = episode.get('seasonNumber') # Hypothèse 1
                if season_number is None:
                    season_number = episode.get('airedSeason') # Hypothèse 2 (fallback)

                if season_number is not None and season_number > 0:
                    episode_counts[season_number] = episode_counts.get(season_number, 0) + 1

            logger.info(f"Nombre d'épisodes par saison (depuis 'default'): {episode_counts}")
            return episode_counts

        except Exception as e:
            logger.error(f"Erreur lors de la récupération des épisodes 'default' pour TVDB ID {tvdb_id}: {e}", exc_info=True)
            return {}