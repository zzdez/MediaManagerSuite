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