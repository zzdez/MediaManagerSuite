
# app/utils/tvdb_client.py
import logging
from flask import current_app
# L'import changera probablement
from tvdb_v4_official import TVDBApi 

logger = logging.getLogger(__name__)

class CustomTVDBClient:
    def __init__(self):
        self.api_key = current_app.config.get('TVDB_API_KEY')
        self.pin = current_app.config.get('TVDB_PIN') # Certaines bibliothèques V4 requièrent un PIN
        if not self.api_key or not self.pin:
            raise ValueError("TVDB_API_KEY et TVDB_PIN doivent être configurés.")
        
        # L'initialisation peut varier
        self.client = TVDBApi(self.api_key, self.pin)

    def get_series_details_by_id(self, tvdb_id, lang='fra'):
        try:
            logger.info(f"Recherche TVDB (lib: tvdb_v4_official) pour l'ID : {tvdb_id} avec la langue '{lang}'")
            
            # La méthode exacte pour obtenir les détails peut varier
            series_data = self.client.get_series_details(tvdb_id, language=lang)
            
            if not series_data:
                return None

            # L'extraction des données peut aussi varier
            details = {
                'title': series_data.get('name'),
                'overview': series_data.get('overview'),
                'status': series_data.get('status'),
                'poster': series_data.get('image_url'),
                'year': series_data.get('firstAired', 'N/A')[:4] # Prend l'année du premier épisode
            }
            return details
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des détails TVDB pour {tvdb_id}: {e}", exc_info=True)
            return None