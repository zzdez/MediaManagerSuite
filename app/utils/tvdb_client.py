# app/utils/tvdb_client.py
import logging
from flask import current_app
from tvdb_v4_official import TVDB # Le vrai import

logger = logging.getLogger(__name__)

class CustomTVDBClient:
    def __init__(self):
        self.api_key = current_app.config.get('TVDB_API_KEY')
        self.pin = current_app.config.get('TVDB_PIN')
        if not self.api_key or not self.pin:
            raise ValueError("TVDB_API_KEY et TVDB_PIN doivent être configurés.")
        
        # La vraie initialisation
        self.client = TVDB(apikey=self.api_key, pin=self.pin)

    def get_series_details_by_id(self, tvdb_id, lang='fra'):
        try:
            logger.info(f"Recherche TVDB (lib: tvdb_v4_official) pour l'ID : {tvdb_id} avec la langue '{lang}'")
            
            # Le vrai appel de méthode
            series_data = self.client.get_series_extended(tvdb_id, meta=lang)
            
            if not series_data:
                logger.warning(f"TVDB n'a rien retourné pour l'ID {tvdb_id}.")
                return None

            logger.info(f"Détails bruts de TVDB reçus pour {tvdb_id}.")
            
            details = {
                'title': series_data.get('name'),
                'overview': series_data.get('overview'),
                'status': series_data.get('status', {}).get('name'),
                'poster': series_data.get('image'),
                'year': series_data.get('year')
            }
            return details
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des détails TVDB pour {tvdb_id}: {e}", exc_info=True)
            return None