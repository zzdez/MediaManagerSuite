import json
import os
from flask import current_app

def _get_settings_file_path():
    """Retourne le chemin complet du fichier de configuration. Doit être appelée dans un contexte d'application."""
    return os.path.join(current_app.instance_path, 'search_settings.json')

def load_search_categories():
    """Charge les catégories de recherche personnalisées depuis le fichier JSON."""
    filepath = _get_settings_file_path()
    default_settings = {
        'sonarr_categories': [5000, 5070, 5080],
        'radarr_categories': [2000, 2060, 2030]
    }
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                settings = json.load(f)
                default_settings.update(settings)
                return default_settings
        return default_settings
    except (IOError, json.JSONDecodeError) as e:
        current_app.logger.error(f"Erreur en lisant {filepath}: {e}")
        return default_settings

def save_search_categories(settings):
    """Sauvegarde les catégories de recherche personnalisées dans le fichier JSON."""
    filepath = _get_settings_file_path()
    try:
        with open(filepath, 'w') as f:
            json.dump(settings, f, indent=4)
        return True
    except IOError as e:
        current_app.logger.error(f"Erreur en écrivant dans {filepath}: {e}")
        return False
