# app/utils/prowlarr_client.py
import requests
from flask import current_app

def _prowlarr_api_request(params):
    """Helper function to make requests to the Prowlarr API."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    # On récupère l'URL et on la traite de manière sûre
    base_url_from_config = config.get('PROWLARR_URL')

    # On vérifie AVANT d'essayer de manipuler la chaîne
    if not api_key or not base_url_from_config:
        current_app.logger.error("Prowlarr URL or API Key is not configured.")
        return None

    # On enlève le / final seulement si la chaîne existe
    base_url = base_url_from_config.rstrip('/')
    
    # L'endpoint de recherche est /api/v1/search pour Prowlarr
    url = f"{base_url}/api/v1/search"
    
    # Le reste de la fonction est inchangé...
    request_params = {'apikey': api_key}
    request_params.update(params)

    try:
        response = requests.get(url, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr API request failed: {e}")
        return None

def search_prowlarr(query, categories=None, year=None, lang=None):
    """
    Searches Prowlarr for a given query and optional categories.

    Args:
        query (str): The search term.
        categories (list of int, optional): List of Prowlarr category IDs.
                                            e.g., [2000] for Movies, [5000] for TV.
        year (str, optional): The year of the media.
        lang (str, optional): The language of the media.

    Returns:
        list: A list of search results, or None if an error occurs.
    """
    params = {'query': query, 'type': 'search'}
    if categories:
        # L'API Prowlarr attend les catégories comme des paramètres répétées
        params['category'] = categories
    if year:
        params['year'] = year
    if lang:
        params['lang'] = lang

    return _prowlarr_api_request(params)
