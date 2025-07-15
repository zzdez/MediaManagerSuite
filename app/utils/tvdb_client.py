# Fichier : app/utils/tvdb_client.py (Version de Diagnostic)

import logging
from tvdb_v4_official import TVDB
from config import Config

logger = logging.getLogger(__name__)

class CustomTVDBClient:
    """
    Client TVDB en mode diagnostic.
    """
    def __init__(self):
        # On log les clés pour vérifier qu'elles sont bien chargées depuis le .env
        self.api_key = Config.TVDB_API_KEY
        self.pin = Config.TVDB_PIN
        self.client = None

        if self.api_key and self.pin:
            # On log une partie des clés pour confirmer le chargement sans exposer les secrets
            logger.info(f"DIAGNOSTIC: Clés TVDB chargées. API Key commence par: '{self.api_key[:4]}...', PIN commence par: '{self.pin[:4]}...'")
        else:
            logger.error("DIAGNOSTIC: Clés TVDB (API Key ou PIN) manquantes dans la configuration !")
        
        self.login()

    def login(self):
        """Initialise et authentifie le client TVDB."""
        if not self.api_key or not self.pin:
            self.client = None
            return

        try:
            logger.info("DIAGNOSTIC: Tentative d'initialisation de TVDB avec les clés fournies.")
            self.client = TVDB(self.api_key, self.pin)
            logger.info("DIAGNOSTIC: Client TVDB initialisé. L'authentification réelle se fera au premier appel.")
        except Exception as e:
            logger.error(f"DIAGNOSTIC: Échec critique lors de l'initialisation de TVDB(): {e}", exc_info=True)
            self.client = None

    def get_series_details_by_id(self, tvdb_id, lang='fra'):
        """
        Récupère les détails d'une série avec un logging de diagnostic maximal.
        """
        if not self.client:
            logger.error("DIAGNOSTIC: Le client n'a pas pu être initialisé. Impossible de continuer.")
            return None

        logger.info(f"DIAGNOSTIC: Début de get_series_details_by_id pour l'ID: {tvdb_id}")
        
        try:
            # --- ÉTAPE DE DIAGNOSTIC LA PLUS IMPORTANTE ---
            logger.info(f"DIAGNOSTIC: Appel de la méthode self.client.get_series({tvdb_id}) ...")
            raw_response = self.client.get_series(tvdb_id)
            logger.info(f"DIAGNOSTIC: Appel terminé. Réponse brute reçue de la librairie.")
            logger.info(f"DIAGNOSTIC: Type de la réponse brute: {type(raw_response)}")
            logger.info(f"DIAGNOSTIC: Contenu de la réponse brute: {raw_response}")
            # --- FIN DE L'ÉTAPE DE DIAGNOSTIC ---

            if not raw_response or 'data' not in raw_response:
                logger.warning(f"DIAGNOSTIC: La réponse brute est vide ou ne contient pas de clé 'data'. L'authentification a probablement échoué ou l'ID n'existe pas.")
                return None
            
            logger.info("DIAGNOSTIC: Données de base trouvées. Extraction en cours.")
            base_data = raw_response['data']
            
            details = {
                'tvdb_id': base_data.get('id'),
                'name': base_data.get('seriesName'),
                'overview': base_data.get('overview', 'Aucun synopsis disponible.'),
                'status': base_data.get('status'),
                'year': base_data.get('year'),
                'image_url': base_data.get('image')
            }

            # On ne se préoccupe pas de la traduction pour l'instant, on veut déjà que ça fonctionne.
            return details

        except Exception as e:
            logger.error(f"DIAGNOSTIC: Une erreur majeure et inattendue est survenue dans get_series_details_by_id: {e}", exc_info=True)
            return None