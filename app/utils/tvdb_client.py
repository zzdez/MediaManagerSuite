# app/utils/tvdb_client.py
import logging
from flask import current_app
from tvdb_v4_official import TVDB

logger = logging.getLogger(__name__)

class CustomTVDBClient:
    def __init__(self):
        self.api_key = current_app.config.get('TVDB_API_KEY')
        self.pin = current_app.config.get('TVDB_PIN')
        if not self.api_key or not self.pin:
            raise ValueError("TVDB_API_KEY and TVDB_PIN must be configured.")
        
        try:
            self.client = TVDB(apikey=self.api_key, pin=self.pin)
            logger.info("TVDB client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize TVDB client: {e}", exc_info=True)
            self.client = None

    def get_series_details_by_id(self, tvdb_id, lang='fra'):
        """
        Récupère les détails d'une série. Privilégie la traduction si elle existe,
        mais retourne toujours les données de base (anglais) si la traduction échoue.
        """
        if not self.client:
            self.login()
            if not self.client:
                logger.error("TVDB client non initialisé, impossible de chercher les détails.")
                return None

        logger.info(f"Recherche TVDB pour l'ID : {tvdb_id}")
        try:
            # Étape 1: On récupère TOUJOURS les données de base de la série
            series_response = self.client.get_series_by_id(tvdb_id)
            if not series_response or 'data' not in series_response:
                logger.warning(f"Aucune donnée de base trouvée pour l'ID TVDB {tvdb_id}")
                return None
            
            base_data = series_response['data']

            # On prépare notre dictionnaire de retour avec les valeurs de base (souvent en anglais)
            details = {
                'tvdb_id': base_data.get('id'),
                'name': base_data.get('seriesName'),
                'overview': base_data.get('overview', 'Aucun synopsis disponible.'),
                'status': base_data.get('status'),
                'year': base_data.get('year'),
                'image_url': base_data.get('image')  # L'URL de l'affiche
            }

            # Étape 2: On TENTE de récupérer la traduction française pour enrichir les données
            logger.info(f"Tentative de récupération de la traduction '{lang}' pour l'ID {tvdb_id}")
            try:
                translation_response = self.client.get_series_translation(tvdb_id, lang)
                if translation_response and 'data' in translation_response and translation_response['data'].get('overview'):
                    logger.info(f"Traduction '{lang}' trouvée. Mise à jour des détails.")
                    # On écrase les champs traductibles avec la version française
                    details['name'] = translation_response['data'].get('name') or details['name']
                    details['overview'] = translation_response['data'].get('overview') or details['overview']
                else:
                    logger.warning(f"Traduction '{lang}' demandée mais non trouvée ou vide pour {tvdb_id}.")
            except Exception as e:
                # On log l'échec de la traduction, mais on ne fait rien, car on a déjà les données de base
                logger.warning(f"Impossible de récupérer la traduction '{lang}' pour {tvdb_id}: {e}")

            return details

        except Exception as e:
            logger.error(f"Erreur majeure lors de la récupération des détails pour l'ID TVDB {tvdb_id}: {e}", exc_info=True)
            return None