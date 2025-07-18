import requests
from flask import current_app

# --- HELPER DE RECHERCHE ---
def _prowlarr_api_request(params):
    """Helper function to make SEARCH requests to the Prowlarr API."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')

    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL or API Key is not configured.")
        return None

    url = f"{base_url}/api/v1/search"
    
    request_params = {'apikey': api_key}
    if params:
        request_params.update(params)

    try:
        response = requests.get(url, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr API SEARCH request failed: {e}")
        return None

# --- FONCTION DE RECHERCHE ---
def search_prowlarr(query, categories=None, lang=None):
    """Searches Prowlarr for a given query and optional filters."""
    effective_query = query
    if lang:
        lang_map = {'fr': 'FRENCH', 'en': 'ENGLISH'}
        lang_term = lang_map.get(lang)
        if lang_term:
            effective_query = f"{query} {lang_term}"

    params = {
        'query': effective_query,
        'type': 'search'
    }
    if categories:
        params['category'] = categories

    return _prowlarr_api_request(params)

# --- FONCTION DE CATÉGORIES (AUTONOME ET CORRIGÉE) ---
def get_prowlarr_categories():
    """Fetches all available categories from the Prowlarr API."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')

    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL or API Key is not configured for category fetching.")
        return []

    # On construit l'URL de l'endpoint CATEGORY manuellement et directement
    url = f"{base_url}/api/v1/category"
    params = {'apikey': api_key}

    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        all_categories = response.json()

        if not isinstance(all_categories, list):
            current_app.logger.error(f"Prowlarr category response is not a list: {all_categories}")
            return []

        # Reformate la réponse pour que le template puisse l'utiliser
        formatted_categories = []
        for cat in all_categories:
            # Créer une structure imbriquée pour les sous-catégories si elles existent
            sub_cats_formatted = []
            if 'subCategories' in cat and isinstance(cat['subCategories'], list):
                for sub in cat['subCategories']:
                     sub_cats_formatted.append({
                         '@attributes': {
                             'id': str(sub.get('id')),
                             'name': sub.get('name')
                         }
                     })

            formatted_categories.append({
                '@attributes': {
                    'id': str(cat.get('id')),
                    'name': cat.get('name')
                },
                'subcat': sub_cats_formatted
            })

        return sorted(formatted_categories, key=lambda x: int(x['@attributes']['id']))

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr API CATEGORY request failed: {e}")
        return []
