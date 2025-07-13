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
        try:
            logger.info(f"Recherche TVDB pour l'ID : {tvdb_id}")
            
            # --- ÉTAPE 1 : Récupérer les données de base (en anglais par défaut) ---
            base_data = self.client.get_series_extended(tvdb_id)
            if not base_data:
                logger.warning(f"TVDB n'a rien retourné pour l'ID {tvdb_id}.")
                return None
            
            # On stocke les détails de base
            details = {
                'title': base_data.get('name'),
                'overview': base_data.get('overview'),
                'status': base_data.get('status', {}).get('name'),
                'poster': base_data.get('image'),
                'year': base_data.get('year')
            }

            # --- ÉTAPE 2 : Récupérer spécifiquement la traduction française ---
            if lang:
                logger.info(f"Tentative de récupération de la traduction '{lang}' pour l'ID {tvdb_id}")
                try:
                    translation_data = self.client.get_series_translation(tvdb_id, lang)
                    if translation_data:
                        logger.info(f"Traduction '{lang}' trouvée. Mise à jour des détails.")
                        # On écrase le titre et le synopsis avec la version traduite si elle existe
                        details['title'] = translation_data.get('name') or details['title']
                        details['overview'] = translation_data.get('overview') or details['overview']
                except Exception as e:
                    logger.warning(f"Impossible de récupérer la traduction '{lang}' pour {tvdb_id}: {e}")

            return details

        except Exception as e:
            logger.error(f"Erreur majeure lors de la récupération des détails TVDB pour {tvdb_id}: {e}", exc_info=True)
            return None