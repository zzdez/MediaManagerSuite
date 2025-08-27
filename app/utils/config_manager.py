# Fichier : app/utils/config_manager.py
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

def load_search_filter_aliases():
    """Charge et parse les alias des filtres de recherche depuis la configuration."""
    import re

    aliases = {}
    # Regex pour trouver les variables d'environnement de nos filtres
    pattern = re.compile(r"^SEARCH_FILTER_(\w+)_(\w+)$")

    for key, value in current_app.config.items():
        match = pattern.match(key)
        if match and value: # S'assurer que la valeur n'est pas vide
            filter_type = match.group(1).lower()  # ex: 'lang'
            filter_value = match.group(2).lower() # ex: 'fr'

            if filter_type not in aliases:
                aliases[filter_type] = {}

            # Sépare les alias par virgule et nettoie les espaces
            aliases[filter_type][filter_value] = [v.strip().lower() for v in value.split(',') if v.strip()]

    return aliases
