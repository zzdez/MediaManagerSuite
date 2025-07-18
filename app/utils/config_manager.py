import json
import os
from flask import current_app

# Le chemin vers notre fichier de configuration, dans le dossier 'instance'
SEARCH_SETTINGS_FILE = os.path.join(current_app.instance_path, 'search_settings.json')

def load_search_categories():
    """Charge les catégories de recherche personnalisées depuis le fichier JSON."""
    default_settings = {
        'sonarr_categories': [5000, 5070, 5080], # Nos valeurs par défaut
        'radarr_categories': [2000, 2060, 2030]
    }
    try:
        if os.path.exists(SEARCH_SETTINGS_FILE):
            with open(SEARCH_SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # S'assure que les clés existent, sinon utilise les valeurs par défaut
                default_settings.update(settings)
                return default_settings
        return default_settings
    except (IOError, json.JSONDecodeError) as e:
        current_app.logger.error(f"Erreur en lisant search_settings.json: {e}")
        return default_settings

def save_search_categories(settings):
    """Sauvegarde les catégories de recherche personnalisées dans le fichier JSON."""
    try:
        with open(SEARCH_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        return True
    except IOError as e:
        current_app.logger.error(f"Erreur en écrivant dans search_settings.json: {e}")
        return False
