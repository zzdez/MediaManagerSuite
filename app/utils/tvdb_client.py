# Fichier : app/utils/tvdb_client.py

import logging
from tvdb_v4_official import TVDB
from config import Config

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
        Récupère les détails d'une série. Corrigé pour lire la réponse directe.
        """
        if not self.client:
            logger.error("Fatal: Le client TVDB ne peut pas être initialisé.")
            return None

        logger.info(f"Recherche TVDB pour l'ID : {tvdb_id}")
        try:
            # Étape 1: Récupération des données de base
            base_data = self.client.get_series(tvdb_id)

            # La réponse est directement le dictionnaire de données.
            if not base_data or not isinstance(base_data, dict):
                logger.warning(f"Aucune donnée valide (ou dictionnaire vide) reçue pour l'ID TVDB {tvdb_id}")
                return None

            logger.info(f"Données de base trouvées pour {tvdb_id}. Nom: {base_data.get('seriesName')}")

            details = {
                'tvdb_id': base_data.get('id'),
                'name': base_data.get('seriesName'),
                'overview': base_data.get('overview', 'Aucun synopsis disponible.'),
                'status': base_data.get('status', {}).get('name', 'Inconnu'), # Accès plus sûr
                'year': base_data.get('year'),
                'image_url': base_data.get('image')
            }

            # Étape 2: Tentative d'enrichissement avec la traduction
            try:
                translation_response = self.client.get_series_translation(tvdb_id, lang)
                if translation_response and translation_response.get('overview'):
                    logger.info(f"Traduction '{lang}' trouvée pour {tvdb_id}.")
                    details['name'] = translation_response.get('name') or details['name']
                    details['overview'] = translation_response.get('overview') or details['overview']
            except Exception as e:
                logger.warning(f"Impossible de récupérer la traduction '{lang}' pour {tvdb_id}: {e}")

            return details

        except Exception as e:
            logger.error(f"Erreur majeure lors de la récupération des détails pour l'ID TVDB {tvdb_id}: {e}", exc_info=True)
            return None
