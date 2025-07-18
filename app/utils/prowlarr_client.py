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


def get_prowlarr_categories():
    """Fetches all available categories from the Prowlarr API."""
    # L'endpoint pour les catégories est /api/v1/category
    params = {} # Pas de paramètre spécifique requis pour cette route

    # On doit appeler l'API différemment ici car _prowlarr_api_request est fait pour la recherche
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url_from_config = config.get('PROWLARR_URL')

    if not api_key or not base_url_from_config:
        current_app.logger.error("Prowlarr URL or API Key is not configured for category fetching.")
        return []

    base_url = base_url_from_config.rstrip('/')
    url = f"{base_url}/api/v1/category"

    try:
        response = requests.get(url, params={'apikey': api_key}, timeout=20)
        response.raise_for_status()
        # On ne retourne que les catégories qui ne sont pas des sous-catégories pour la simplicité
        all_categories = response.json()
        return sorted(all_categories, key=lambda x: x['id'])
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr API request for categories failed: {e}")
        return []

def search_prowlarr(query, categories=None, lang=None):
    """
    Searches Prowlarr for a given query and optional filters.
    Prowlarr's direct filtering capabilities are limited via API,
    so complex filtering (like year, quality) will be done post-retrieval.
    """
    params = {
        'query': query,
        'type': 'search'
    }
    if categories:
        params['category'] = categories

    # Le filtrage par langue peut parfois être ajouté à la query
    # Prowlarr ne gère pas un paramètre 'lang' directement dans la recherche.
    # On l'ajoute au terme de recherche, ce qui est une heuristique courante.
    effective_query = query
    if lang:
        lang_map = {'fr': 'FRENCH', 'en': 'ENGLISH'} # Peut être étendu
        lang_term = lang_map.get(lang)
        if lang_term:
            effective_query = f"{query} {lang_term}"

    params['query'] = effective_query

    return _prowlarr_api_request(params)
