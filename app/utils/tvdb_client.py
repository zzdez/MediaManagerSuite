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
        if not self.client:
            logger.error("TVDB client is not initialized.")
            return None

        try:
            logger.info(f"Fetching TVDB details for ID: {tvdb_id} with language '{lang}'")
            
            series_data = self.client.get_series_extended(tvdb_id, meta=lang, short=False)
            
            if not series_data:
                logger.warning(f"No data returned from TVDB for ID {tvdb_id}.")
                return None

            logger.debug(f"Raw TVDB details received for {tvdb_id}: {series_data}")
            
            details = {
                'title': series_data.get('name'),
                'overview': series_data.get('overview'),
                'status': series_data.get('status', {}).get('name'),
                'poster_path': series_data.get('image'),
                'year': series_data.get('year'),
                'tvdb_id': series_data.get('id')
            }
            return details
        except Exception as e:
            logger.error(f"Error fetching TVDB details for {tvdb_id}: {e}", exc_info=True)
            return None