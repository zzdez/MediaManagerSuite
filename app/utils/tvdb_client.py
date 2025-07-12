# app/utils/tvdb_client.py
import logging
from flask import current_app
from thetvdb_api import TVDB

logger = logging.getLogger(__name__)

class TheTVDBClient:
    def __init__(self):
        self.api_key = current_app.config.get('TVDB_API_KEY')
        if not self.api_key:
            raise ValueError("La clé API TVDB (TVDB_API_KEY) n'est pas configurée.")
        self.client = TVDB(api_key=self.api_key)

    def get_series_details_by_id(self, tvdb_id, lang='fra'):
        """
        Récupère les détails d'une série depuis TVDB en utilisant son ID.
        Tente de récupérer les données en français par défaut.
        """
        try:
            logger.info(f"Recherche TVDB (lib: thetvdb_api) pour l'ID : {tvdb_id} avec la langue '{lang}'")
            series_data = self.client.get_series_extended(tvdb_id, lang=lang) # Vérifie le nom de cette méthode

            if not series_data:
                logger.warning(f"TVDB n'a rien retourné pour l'ID {tvdb_id}.")
                return None

            logger.info(f"Détails bruts de TVDB reçus pour {tvdb_id}.")
            # On extrait les informations qui nous intéressent
            details = {
                'title': series_data.get('name'),
                'overview': series_data.get('overview'),
                'status': series_data.get('status', {}).get('name'),
                'poster': series_data.get('image'),
                'year': series_data.get('year')
                # Ajoute d'autres champs si nécessaire
            }
            return details
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des détails TVDB pour {tvdb_id}: {e}", exc_info=True)
            return None
