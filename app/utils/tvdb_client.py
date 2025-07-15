# Fichier : app/utils/tvdb_client.py

import logging
from tvdb_v4_official import TVDB
from app.config import Config

logger = logging.getLogger(__name__)

class CustomTVDBClient:
    """
    Client TVDB personnalisé pour gérer la connexion et les appels API.
    """
    def __init__(self):
        self.api_key = Config.TVDB_API_KEY
        self.pin = Config.TVDB_PIN
        self.client = None
        self.login()

    def login(self):
        """Initialise et authentifie le client TVDB."""
        try:
            if self.api_key and self.pin:
                self.client = TVDB(self.api_key, self.pin)
                logger.info("TVDB client initialized successfully.")
            else:
                logger.error("TVDB API key or PIN is missing from configuration.")
                self.client = None
        except Exception as e:
            logger.error(f"Failed to initialize TVDB client: {e}", exc_info=True)
            self.client = None

    def get_series_details_by_id(self, tvdb_id, lang='fra'):
        """
        Récupère les détails d'une série. Robuste et avec fallback.
        """
        if not self.client:
            logger.warning("TVDB client not authenticated. Attempting to log in again.")
            self.login()
            if not self.client:
                logger.error("Fatal: TVDB client cannot be initialized.")
                return None

        logger.info(f"Recherche TVDB pour l'ID : {tvdb_id}")
        try:
            # Étape 1: Récupération des données de base
            series_response = self.client.get_series(tvdb_id)
            if not series_response or 'data' not in series_response:
                logger.warning(f"Aucune donnée de base trouvée pour l'ID TVDB {tvdb_id}")
                return None

            base_data = series_response['data']

            details = {
                'tvdb_id': base_data.get('id'),
                'name': base_data.get('seriesName'),
                'overview': base_data.get('overview', 'Aucun synopsis disponible.'),
                'status': base_data.get('status'),
                'year': base_data.get('year'),
                'image_url': base_data.get('image')
            }

            # Étape 2: Tentative d'enrichissement avec la traduction
            try:
                translation_response = self.client.get_series_translation(tvdb_id, lang)
                if translation_response and 'data' in translation_response and translation_response['data'].get('overview'):
                    logger.info(f"Traduction '{lang}' trouvée pour {tvdb_id}.")
                    details['name'] = translation_response['data'].get('name') or details['name']
                    details['overview'] = translation_response['data'].get('overview') or details['overview']
            except Exception as e:
                logger.warning(f"Impossible de récupérer la traduction '{lang}' pour {tvdb_id}: {e}")

            return details

        except Exception as e:
            logger.error(f"Erreur majeure lors de la récupération des détails pour l'ID TVDB {tvdb_id}: {e}", exc_info=True)
            return None
