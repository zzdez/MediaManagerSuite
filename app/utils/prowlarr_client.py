# app/utils/prowlarr_client.py
import requests
from flask import current_app

def _make_prowlarr_request(endpoint, params=None):
    # ... (Cette fonction est déjà correcte)
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')
    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL or API Key not configured.")
        return None
    url = f"{base_url}/api/v1/{endpoint.lstrip('/')}"
    request_params = {'apikey': api_key}
    if params:
        request_params.update(params)
    try:
        response = requests.get(url, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr API request for endpoint '{endpoint}' failed: {e}")
        return None

def search_prowlarr(query, categories=None, lang=None):
    # ... (Cette fonction est déjà correcte)
    effective_query = query
    if lang:
        lang_map = {'fr': 'FRENCH', 'en': 'ENGLISH'}
        lang_term = lang_map.get(lang)
        if lang_term:
            effective_query = f"{query} {lang_term}"
    params = {'query': effective_query, 'type': 'search'}
    if categories:
        params['category'] = categories
    return _make_prowlarr_request('search', params)

def get_prowlarr_categories():
    """
    [STRATÉGIE FINALE v2] Fetches all categories by querying the details
    of a reliable indexer known to have the full category list.
    """
    try:
        master_indexer_id = 11  # Ygg
        current_app.logger.info(f"Prowlarr: Using master indexer ID {master_indexer_id} to fetch category list.")
        indexer_details = _make_prowlarr_request(f'indexer/{master_indexer_id}')

        if not indexer_details or 'capabilities' not in indexer_details or 'categories' not in indexer_details['capabilities']:
             raise ValueError(f"Could not extract 'capabilities.categories' path from indexer {master_indexer_id}.")

        all_categories = indexer_details['capabilities']['categories']
        current_app.logger.info(f"Prowlarr: Found {len(all_categories)} categories successfully via master indexer.")
        
        formatted_categories = []
        for cat in all_categories:
            if cat.get('name'):
                formatted_categories.append({
                    '@attributes': {
                        'id': str(cat.get('id')),
                        'name': cat.get('name')
                    }
                })
        return sorted(formatted_categories, key=lambda x: int(x['@attributes']['id']))
    except Exception as e:
        current_app.logger.error(f"Failed to fetch categories via master indexer: {e}", exc_info=True)
        return []