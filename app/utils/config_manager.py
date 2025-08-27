# Fichier : app/utils/config_manager.py
import json
import os
from flask import current_app

def load_search_categories():
    """Charge les catégories de recherche depuis la configuration."""
    search_config = {
        'sonarr_categories': current_app.config.get('SONARR_CATEGORIES', []),
        'radarr_categories': current_app.config.get('RADARR_CATEGORIES', [])
    }
    return search_config

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
